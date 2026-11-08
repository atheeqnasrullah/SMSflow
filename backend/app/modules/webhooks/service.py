"""Signed webhook events with retries, SSRF protection and auto-disable."""

from __future__ import annotations

import ipaddress
import json
import secrets
import socket
import time
import uuid
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import tenant_session, utcnow
from app.core.errors import ValidationFailed
from app.core.security import decrypt_str, encrypt_str, webhook_signature
from app.modules.webhooks.models import WEBHOOK_EVENTS, WebhookDelivery, WebhookEndpoint
from app.workers.dispatch import defer

RETRY_SCHEDULE = [60, 300, 1800, 7200, 21600, 43200]  # 1m 5m 30m 2h 6h 12h (≈ 21 h total)


class UnsafeUrl(ValueError):
    pass


def _ip_is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return not (
        addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast
        or addr.is_reserved or addr.is_unspecified
    )


def check_url_safe(url: str) -> None:
    parsed = urlparse(url)
    allow_private = settings.webhook_allow_private_targets or settings.env in ("local", "test")
    if parsed.scheme != "https" and not (allow_private and parsed.scheme == "http"):
        raise UnsafeUrl("Webhook URL must use HTTPS")
    if not parsed.hostname:
        raise UnsafeUrl("Webhook URL has no host")
    if allow_private:
        return
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeUrl("Webhook host does not resolve") from exc
    for info in infos:
        if not _ip_is_public(str(info[4][0])):
            raise UnsafeUrl("Webhook URL resolves to a non-public address")


def validate_events(events: list[str]) -> list[str]:
    bad = [e for e in events if e not in WEBHOOK_EVENTS]
    if bad:
        raise ValidationFailed(f"Unknown events: {', '.join(bad)}")
    return sorted(set(events))


def new_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(32)


async def create_endpoint(
    session: AsyncSession, tenant_id: uuid.UUID, url: str, events: list[str], description: str | None
) -> tuple[WebhookEndpoint, str]:
    try:
        check_url_safe(url)
    except UnsafeUrl as exc:
        raise ValidationFailed(str(exc), code="unsafe_url") from exc
    secret = new_secret()
    ep = WebhookEndpoint(
        tenant_id=tenant_id, url=url, description=description,
        events=validate_events(events), secret_encrypted=encrypt_str(secret),
    )
    session.add(ep)
    await session.flush()
    return ep, secret


async def emit(session: AsyncSession, tenant_id: uuid.UUID, event_type: str, data: dict[str, Any]) -> int:
    """Create deliveries for subscribed endpoints (dispatched after the caller commits)."""
    endpoints = (
        await session.scalars(
            select(WebhookEndpoint).where(
                WebhookEndpoint.tenant_id == tenant_id, WebhookEndpoint.is_active.is_(True)
            )
        )
    ).all()
    count = 0
    for ep in endpoints:
        if event_type not in (ep.events or []):
            continue
        delivery = WebhookDelivery(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            endpoint_id=ep.id,
            event_type=event_type,
            payload={"id": None, "type": event_type, "created_at": utcnow().isoformat(), "data": data},
        )
        delivery.payload["id"] = f"evt_{delivery.id.hex}"
        session.add(delivery)
        defer(session, "webhooks.deliver", delivery_id=delivery.id, tenant_id=tenant_id)
        count += 1
    return count


async def deliver(delivery_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    async with tenant_session(tenant_id) as s:
        d = await s.get(WebhookDelivery, delivery_id)
        if d is None or d.status == "succeeded":
            return
        ep = await s.get(WebhookEndpoint, d.endpoint_id)
        if ep is None or not ep.is_active:
            d.status = "failed"
            d.response_body = "endpoint disabled"
            await s.commit()
            return
        body = json.dumps(d.payload, separators=(",", ":"), default=str).encode()
        ts = int(time.time())
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "SMSFlow-Webhooks/1.0",
            "SMSFlow-Event": d.event_type,
            "SMSFlow-Delivery": f"whd_{d.id.hex}",
            "SMSFlow-Timestamp": str(ts),
            "SMSFlow-Signature": webhook_signature(decrypt_str(ep.secret_encrypted), ts, body),
        }
        d.attempt += 1
        status_code: int | None = None
        text = ""
        try:
            check_url_safe(ep.url)  # re-check at delivery time (DNS rebinding)
            async with httpx.AsyncClient(timeout=settings.webhook_timeout_seconds, follow_redirects=False) as client:
                resp = await client.post(ep.url, content=body, headers=headers)
            status_code, text = resp.status_code, resp.text[:1000]
        except (httpx.HTTPError, UnsafeUrl) as exc:
            text = f"{type(exc).__name__}: {exc}"[:1000]
        d.response_status = status_code
        d.response_body = text
        if status_code is not None and 200 <= status_code < 300:
            d.status = "succeeded"
            d.delivered_at = utcnow()
            d.next_retry_at = None
            ep.consecutive_failures = 0
        else:
            ep.consecutive_failures += 1
            if ep.consecutive_failures >= settings.webhook_disable_after_failures:
                ep.is_active = False
                ep.disabled_reason = f"Disabled after {ep.consecutive_failures} consecutive failures"
            if d.attempt <= len(RETRY_SCHEDULE) and ep.is_active:
                delay = RETRY_SCHEDULE[d.attempt - 1]
                d.status = "pending"
                d.next_retry_at = utcnow() + timedelta(seconds=delay)
                defer(s, "webhooks.deliver", countdown=delay, delivery_id=d.id, tenant_id=tenant_id)
            else:
                d.status = "failed"
                d.next_retry_at = None
        await s.commit()

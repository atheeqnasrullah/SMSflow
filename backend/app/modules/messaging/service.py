"""Messaging engine: validation, costing, message creation, provider submission and DLR handling."""

from __future__ import annotations

import random
import re
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import system_session, tenant_session, utcnow
from app.core.errors import Forbidden, InsufficientFunds, ValidationFailed
from app.modules.contacts.models import Suppression
from app.modules.messaging.models import Message, MessageEvent
from app.modules.providers import router as provider_router
from app.modules.providers.base import OutboundSms, SendResult
from app.modules.sender_ids.models import SenderId
from app.modules.tenants.models import Tenant
from app.modules.wallet import service as wallet_service
from app.shared import phone as phone_util
from app.shared.money import ZERO, money
from app.shared.sms_segments import analyze
from app.workers.dispatch import defer

log = structlog.get_logger("smsflow.messaging")

OPT_OUT_RE = re.compile(r"\b(stop|unsubscribe|opt[\s-]?out)\b", re.IGNORECASE)
SENDER_RE = re.compile(r"^(?=.*[A-Za-z])[A-Za-z0-9 .\-]{1,11}$|^[0-9]{3,15}$")


# --- Validation helpers ---------------------------------------------------------------------
def ensure_tenant_active(tenant: Tenant) -> None:
    if tenant.status != "active":
        raise Forbidden("Workspace is suspended; sending is disabled", code="tenant_suspended")


def is_demo_send(tenant: Tenant, principal: Any | None = None) -> bool:
    return tenant.mode == "demo" or bool(principal is not None and getattr(principal, "is_test_key", False))


async def resolve_sender(session: AsyncSession, tenant_id: uuid.UUID, sender: str | None, *, is_demo: bool) -> str:
    if is_demo:
        return (sender or settings.demo_default_sender)[:11]
    approved = (
        await session.scalars(
            select(SenderId.value).where(SenderId.tenant_id == tenant_id, SenderId.status == "approved")
        )
    ).all()
    if sender is None:
        if len(approved) == 1:
            return approved[0]
        raise ValidationFailed("sender_id is required", code="sender_id_required")
    if sender not in approved:
        raise ValidationFailed(f"Sender ID '{sender}' is not approved for this workspace", code="sender_id_not_approved")
    return sender


def check_content(body: str, category: str) -> None:
    if not body or not body.strip():
        raise ValidationFailed("Message body is empty")
    if len(body) > 1600:
        raise ValidationFailed("Message body too long (max 1600 characters)")
    if category == "promotional" and not OPT_OUT_RE.search(body):
        raise ValidationFailed(
            "Promotional messages must include an opt-out instruction (e.g. 'Reply STOP to opt out')",
            code="opt_out_required",
        )


async def suppressed_numbers(session: AsyncSession, tenant_id: uuid.UUID, numbers: list[str]) -> set[str]:
    if not numbers:
        return set()
    out: set[str] = set()
    for i in range(0, len(numbers), 1000):
        chunk = numbers[i : i + 1000]
        rows = await session.scalars(
            select(Suppression.phone_e164).where(
                Suppression.tenant_id == tenant_id, Suppression.phone_e164.in_(chunk)
            )
        )
        out.update(rows)
    return out


async def check_daily_cap(session: AsyncSession, tenant: Tenant, adding: int) -> None:
    """New-tenant sending cap (abuse control) for live traffic."""
    if tenant.created_at > utcnow() - timedelta(days=7):
        since = utcnow() - timedelta(days=1)
        sent = await session.scalar(
            select(func.count(Message.id)).where(
                Message.tenant_id == tenant.id, Message.is_demo.is_(False), Message.created_at >= since
            )
        )
        if int(sent or 0) + adding > settings.new_tenant_daily_cap:
            raise Forbidden(
                f"New workspaces are limited to {settings.new_tenant_daily_cap} messages per day. "
                "Contact support to raise the limit.",
                code="daily_cap_reached",
            )


def add_event(session: AsyncSession, msg: Message, status: str, raw: dict[str, Any] | None = None) -> None:
    session.add(MessageEvent(tenant_id=msg.tenant_id, message_id=msg.id, status=status, raw_payload=raw or {}))


def message_payload(msg: Message) -> dict[str, Any]:
    return {
        "message_id": str(msg.id),
        "status": msg.status,
        "to": msg.to_e164,
        "sender": msg.sender,
        "segments": msg.segments,
        "encoding": msg.encoding,
        "cost": float(msg.cost),
        "currency": settings.currency,
        "is_demo": msg.is_demo,
        "campaign_id": str(msg.campaign_id) if msg.campaign_id else None,
        "source": msg.source,
        "error_code": msg.error_code,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
        "submitted_at": msg.submitted_at.isoformat() if msg.submitted_at else None,
        "delivered_at": msg.delivered_at.isoformat() if msg.delivered_at else None,
    }


# --- Single / API sends ----------------------------------------------------------------------
async def create_single_message(
    session: AsyncSession,
    *,
    tenant: Tenant,
    principal: Any,
    to: str,
    body: str,
    sender: str | None,
    category: str = "transactional",
    source: str = "api",
    idempotency_key: str | None = None,
    metadata: dict[str, Any] | None = None,
    priority: bool = True,
) -> Message:
    """Validate, reserve funds and queue one message. Caller commits (tasks dispatch after commit)."""
    ensure_tenant_active(tenant)
    check_content(body, category)
    try:
        to_e164 = phone_util.normalize(to)
    except phone_util.InvalidPhoneNumber as exc:
        raise ValidationFailed(f"Invalid phone number: {to}", code="invalid_number") from exc
    if await suppressed_numbers(session, tenant.id, [to_e164]):
        raise ValidationFailed("Recipient has opted out / is suppressed", code="suppressed")

    demo = is_demo_send(tenant, principal)
    sender_value = await resolve_sender(session, tenant.id, sender, is_demo=demo)
    info = analyze(body)
    if not demo:
        await check_daily_cap(session, tenant, 1)

    wallet = await wallet_service.get_wallet(session, tenant.id, for_update=True)
    msg = Message(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        source=source,
        category=category,
        to_e164=to_e164,
        sender=sender_value,
        body=body,
        encoding=info.encoding,
        segments=info.segments,
        is_demo=demo,
        api_key_id=getattr(principal, "api_key_id", None),
        idempotency_key=idempotency_key,
        metadata_=metadata or {},
        status="queued",
    )
    if demo:
        await wallet_service.consume_demo_credits(session, wallet, info.segments)
        msg.unit_price = ZERO
        msg.cost = ZERO
    else:
        unit = await wallet_service.price_per_segment(session, tenant.id, category)
        msg.unit_price = unit
        msg.cost = money(unit * info.segments)
        await wallet_service.reserve(
            session, wallet, msg.cost, key=f"reserve:msg:{msg.id}", reference_type="message", reference_id=msg.id
        )
        msg.reserved_amount = msg.cost
    session.add(msg)
    add_event(session, msg, "queued")
    await session.flush()
    defer(
        session,
        "messaging.send_priority" if priority else "messaging.send_message",
        message_id=msg.id,
        tenant_id=tenant.id,
    )
    return msg


# --- Worker: submit to provider ----------------------------------------------------------------
def _backoff(attempt: int) -> float:
    base = min(600, 10 * 2 ** max(0, attempt - 1))
    return base + random.uniform(0, base / 4)


async def _release_message_reservation(session: AsyncSession, msg: Message) -> None:
    if msg.is_demo or msg.charged or money(msg.reserved_amount) <= 0:
        return
    wallet = await wallet_service.get_wallet(session, msg.tenant_id, for_update=True)
    await wallet_service.release(
        session, wallet, msg.reserved_amount, key=f"release:msg:{msg.id}", reference_type="message", reference_id=msg.id
    )
    msg.reserved_amount = ZERO


async def finish_failed(session: AsyncSession, msg: Message, status: str, code: str, message: str | None) -> None:
    msg.status = status
    msg.error_code = code
    msg.error_message = message
    await _release_message_reservation(session, msg)
    add_event(session, msg, status, {"error_code": code, "error_message": message})
    from app.modules.webhooks.service import emit

    await emit(session, msg.tenant_id, "message.failed", message_payload(msg))
    if msg.campaign_id:
        defer(session, "campaigns.check_completion", campaign_id=msg.campaign_id, tenant_id=msg.tenant_id)


async def submit_message(message_id: uuid.UUID, tenant_id: uuid.UUID, *, priority: bool) -> None:
    """Phase 1 (locked): validate & mark submitting. Phase 2: call provider. Phase 3: record result."""
    from app.modules.campaigns.models import Campaign

    task_name = "messaging.send_priority" if priority else "messaging.send_message"
    async with tenant_session(tenant_id) as s:
        msg = await s.scalar(select(Message).where(Message.id == message_id).with_for_update())
        if msg is None or msg.status != "queued":
            return  # idempotent: already handled
        tenant = await s.get(Tenant, tenant_id)
        assert tenant is not None
        if msg.campaign_id:
            camp = await s.get(Campaign, msg.campaign_id)
            if camp is not None and camp.status == "paused":
                return  # resume re-enqueues queued messages
            if camp is not None and camp.status == "cancelled":
                await finish_failed(s, msg, "rejected", "campaign_cancelled", None)
                await s.commit()
                return
        if tenant.status != "active":
            await finish_failed(s, msg, "rejected", "tenant_suspended", None)
            await s.commit()
            return

        provider_row = None
        if msg.is_demo:
            adapter = provider_router.demo_provider()
            code = "demo"
        else:
            rows = await provider_router.select_providers(s, msg.category)
            if not rows:
                msg.attempts += 1
                if msg.attempts >= settings.max_send_attempts:
                    await finish_failed(s, msg, "failed", "no_provider", "No active SMS provider configured")
                else:
                    defer(s, task_name, countdown=_backoff(msg.attempts), message_id=msg.id, tenant_id=tenant_id)
                await s.commit()
                return
            provider_row = rows[0]
            # Bulk campaigns never fail over (avoids duplicate sends across providers): wait instead.
            if msg.source == "campaign" and not await provider_router.is_healthy(provider_row.code):
                defer(s, task_name, countdown=60, message_id=msg.id, tenant_id=tenant_id)
                await s.commit()
                return
            if not await provider_router.acquire_tps_slot(provider_row.code, provider_row.max_tps):
                defer(s, task_name, countdown=1 + random.random(), message_id=msg.id, tenant_id=tenant_id)
                await s.commit()
                return
            adapter = provider_router.build_adapter(provider_row)
            code = provider_row.code
            # Make sure the full cost is reserved before anything leaves the building.
            shortfall = money(msg.cost) - money(msg.reserved_amount)
            if shortfall > 0:
                wallet = await wallet_service.get_wallet(s, tenant_id, for_update=True)
                try:
                    await wallet_service.reserve(
                        s, wallet, shortfall, key=f"reserve:msg:{msg.id}:extra",
                        reference_type="message", reference_id=msg.id,
                    )
                    msg.reserved_amount = money(msg.reserved_amount) + shortfall
                except InsufficientFunds:
                    await finish_failed(s, msg, "failed", "insufficient_funds", "Wallet balance too low")
                    await s.commit()
                    return

        msg.status = "submitting"
        msg.attempts += 1
        msg.provider_code = code
        msg.provider_id = provider_row.id if provider_row else None
        outbound = OutboundSms(
            message_id=str(msg.id), to=msg.to_e164, sender=msg.sender, body=msg.body, encoding=msg.encoding,
            segments=msg.segments, tenant_id=str(tenant_id), category=msg.category,
        )
        await s.commit()

    try:
        result = await adapter.send(outbound)
    except Exception as exc:  # adapters should not raise, but never lose a message if they do
        log.exception("provider_send_crashed", provider=code)
        result = SendResult("retryable_error", error_code="ADAPTER_ERROR", error_message=str(exc)[:500])
    await provider_router.record_result(code, result.outcome != "retryable_error")

    await record_send_result(message_id, tenant_id, result, task_name=task_name)


async def record_send_result(message_id: uuid.UUID, tenant_id: uuid.UUID, result: SendResult, *, task_name: str) -> None:
    from app.modules.webhooks.service import emit

    async with tenant_session(tenant_id) as s:
        msg = await s.scalar(select(Message).where(Message.id == message_id).with_for_update())
        if msg is None or msg.status != "submitting":
            return
        if result.outcome == "accepted":
            msg.status = "accepted"
            msg.provider_message_id = result.provider_message_id
            msg.submitted_at = utcnow()
            if not msg.is_demo:
                wallet = await wallet_service.get_wallet(s, tenant_id, for_update=True)
                await wallet_service.charge(
                    s, wallet, msg.cost, from_reserved=msg.reserved_amount, key=f"charge:msg:{msg.id}",
                    reference_type="message", reference_id=msg.id,
                )
                msg.charged = True
                msg.reserved_amount = ZERO
                if wallet_service.needs_low_balance_alert(wallet):
                    wallet.low_balance_notified_at = utcnow()
                    await emit(s, tenant_id, "wallet.low_balance", {
                        "available": float(wallet_service.available(wallet)),
                        "threshold": float(wallet.low_balance_threshold),
                        "currency": wallet.currency,
                    })
                    defer(s, "wallet.notify_low_balance", tenant_id=tenant_id)
            add_event(s, msg, "accepted", result.raw)
            await emit(s, tenant_id, "message.accepted", message_payload(msg))
            if msg.is_demo:
                final, delay = provider_router.demo_provider().simulate_outcome(msg.to_e164)
                if final:
                    defer(
                        s, "messaging.process_dlr", countdown=delay, provider_code="demo",
                        provider_message_id=msg.provider_message_id, status=final, error_code=None,
                        raw={"demo": True, "status": final},
                    )
            if msg.campaign_id:
                defer(s, "campaigns.check_completion", campaign_id=msg.campaign_id, tenant_id=tenant_id)
        elif result.outcome == "retryable_error" and msg.attempts < settings.max_send_attempts:
            msg.status = "queued"
            msg.error_code = result.error_code
            msg.error_message = result.error_message
            add_event(s, msg, "retry", {"error_code": result.error_code, "attempt": msg.attempts})
            defer(s, task_name, countdown=_backoff(msg.attempts), message_id=msg.id, tenant_id=tenant_id)
        else:
            await finish_failed(s, msg, "failed", result.error_code or "send_failed", result.error_message)
        await s.commit()


# --- Delivery reports --------------------------------------------------------------------------
ALLOWED_DLR_FROM = {"accepted", "unknown"}


async def apply_dlr(
    provider_code: str,
    provider_message_id: str,
    status: str,
    *,
    error_code: str | None = None,
    raw: dict[str, Any] | None = None,
) -> bool:
    """Apply one delivery report. Idempotent. Returns True if the message changed."""
    from app.modules.webhooks.service import emit

    async with system_session() as sys:
        ref = (
            await sys.execute(
                select(Message.id, Message.tenant_id).where(
                    Message.provider_code == provider_code, Message.provider_message_id == provider_message_id
                )
            )
        ).first()
    if ref is None:
        log.warning("dlr_unknown_message", provider=provider_code, provider_message_id=provider_message_id)
        return False
    message_id, tenant_id = ref

    async with tenant_session(tenant_id) as s:
        msg = await s.scalar(select(Message).where(Message.id == message_id).with_for_update())
        if msg is None:
            return False
        add_event(s, msg, f"dlr:{status}", raw or {})
        if status == "accepted" or msg.status not in ALLOWED_DLR_FROM or status == msg.status:
            await s.commit()
            return False
        if status not in ("delivered", "undelivered", "unknown"):
            await s.commit()
            return False
        msg.status = status
        if status == "delivered":
            msg.delivered_at = utcnow()
            await emit(s, tenant_id, "message.delivered", message_payload(msg))
        elif status == "undelivered":
            msg.error_code = error_code or msg.error_code or "undelivered"
            if settings.refund_undelivered and msg.charged and not msg.is_demo:
                wallet = await wallet_service.get_wallet(s, tenant_id, for_update=True)
                await wallet_service.credit(
                    s, wallet, msg.cost, entry_type="refund", key=f"refund:msg:{msg.id}",
                    reference_type="message", reference_id=msg.id, description="Undelivered message refund",
                )
            await emit(s, tenant_id, "message.failed", message_payload(msg))
        if msg.campaign_id:
            defer(s, "campaigns.refresh_stats", campaign_id=msg.campaign_id, tenant_id=tenant_id)
        await s.commit()
        return True


async def requeue_campaign_messages(session: AsyncSession, campaign_id: uuid.UUID, tenant_id: uuid.UUID) -> int:
    ids = (
        await session.scalars(
            select(Message.id).where(Message.campaign_id == campaign_id, Message.status == "queued")
        )
    ).all()
    for mid in ids:
        defer(session, "messaging.send_message", message_id=mid, tenant_id=tenant_id)
    return len(ids)


def estimate_cost(segments: int, unit_price: Decimal) -> Decimal:
    return money(unit_price * segments)

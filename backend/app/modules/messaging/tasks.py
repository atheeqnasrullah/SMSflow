from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.core.db import system_session, utcnow
from app.modules.messaging import service
from app.modules.messaging.models import Message
from app.modules.providers import router as provider_router
from app.workers.dispatch import enqueue
from app.workers.registry import task


@task("messaging.send_message", queue="sms.send")
async def send_message(message_id: str, tenant_id: str) -> None:
    await service.submit_message(uuid.UUID(message_id), uuid.UUID(tenant_id), priority=False)


@task("messaging.send_priority", queue="sms.priority")
async def send_priority(message_id: str, tenant_id: str) -> None:
    await service.submit_message(uuid.UUID(message_id), uuid.UUID(tenant_id), priority=True)


@task("messaging.process_dlr", queue="dlr")
async def process_dlr(
    provider_code: str,
    provider_message_id: str,
    status: str,
    error_code: str | None = None,
    raw: dict[str, Any] | None = None,
) -> None:
    await service.apply_dlr(provider_code, provider_message_id, status, error_code=error_code, raw=raw)


@task("messaging.poll_pending_dlrs", queue="dlr")
async def poll_pending_dlrs() -> None:
    """Query providers for messages without DLR; mark 'unknown' after the DLR window."""
    now = utcnow()
    async with system_session() as s:
        stale = (
            await s.execute(
                select(Message.provider_code, Message.provider_message_id, Message.submitted_at)
                .where(Message.status == "accepted", Message.submitted_at < now - timedelta(minutes=15))
                .limit(5000)
            )
        ).all()
        providers = {}
        for code, pmid, submitted_at in stale:
            if submitted_at < now - timedelta(hours=settings.dlr_unknown_after_hours):
                await service.apply_dlr(code, pmid, "unknown", raw={"reason": "dlr_window_expired"})
                continue
            if code == "demo":
                continue
            if code not in providers:
                row = await provider_router.get_provider_by_code(s, code)
                providers[code] = provider_router.build_adapter(row) if row else None
            adapter = providers[code]
            if adapter is None:
                continue
            report = await adapter.get_status(pmid)
            if report and report.status in ("delivered", "undelivered"):
                await service.apply_dlr(code, pmid, report.status, error_code=report.error_code, raw=report.raw)


@task("messaging.sweep_stuck", queue="default")
async def sweep_stuck() -> None:
    """Redis is not the source of truth: re-enqueue messages stuck in 'queued'/'submitting'."""
    cutoff = utcnow() - timedelta(minutes=10)
    async with system_session() as s:
        rows = (
            await s.execute(
                select(Message.id, Message.tenant_id, Message.status, Message.source)
                .where(Message.status.in_(("queued", "submitting")), Message.updated_at < cutoff)
                .limit(10000)
            )
        ).all()
        for mid, tid, status, source in rows:
            if status == "submitting":
                # Unknown whether the provider got it: mark for review instead of risking a duplicate.
                msg = await s.get(Message, mid)
                if msg is not None:
                    msg.status = "unknown"
                    msg.error_code = "submit_interrupted"
                continue
            name = "messaging.send_message" if source == "campaign" else "messaging.send_priority"
            await enqueue(name, message_id=mid, tenant_id=tid)
        await s.commit()

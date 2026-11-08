"""Public send API (also used by the dashboard): /sms/send, /sms/bulk, /sms, /sms/{id}."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.config import settings
from app.core.deps import Principal, RateLimit, TenantSession, require
from app.core.errors import AppError, NotFound, ValidationFailed
from app.core.idempotency import run_idempotent
from app.core.permissions import P
from app.modules.messaging import service
from app.modules.messaging.models import Message, MessageEvent
from app.modules.tenants.models import Tenant
from app.shared.pagination import Page, PageParams, page_params, paginate
from app.shared.sms_segments import analyze

router = APIRouter(prefix="/sms", tags=["sms"], dependencies=[RateLimit])


class SendIn(BaseModel):
    to: str = Field(examples=["+94771234567"])
    message: str = Field(min_length=1, max_length=1600)
    sender_id: str | None = Field(default=None, max_length=15)
    category: str = Field(default="transactional", pattern="^(transactional|promotional)$")
    metadata: dict[str, Any] = Field(default_factory=dict)


class BulkItem(BaseModel):
    to: str
    message: str = Field(min_length=1, max_length=1600)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BulkIn(BaseModel):
    messages: list[BulkItem] = Field(min_length=1)
    sender_id: str | None = None
    category: str = Field(default="transactional", pattern="^(transactional|promotional)$")


class SegmentsIn(BaseModel):
    message: str = Field(max_length=5000)


async def _tenant(session: TenantSession, principal: Principal) -> Tenant:
    t = await session.get(Tenant, principal.tenant_id)
    assert t is not None
    return t


@router.post("/send", status_code=202, responses={202: {"description": "Queued"}})
async def send_sms(
    data: SendIn,
    session: TenantSession,
    principal: Principal = Depends(require(P.MESSAGES_SEND)),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JSONResponse:
    tenant = await _tenant(session, principal)

    async def action() -> tuple[int, dict[str, Any]]:
        msg = await service.create_single_message(
            session, tenant=tenant, principal=principal, to=data.to, body=data.message, sender=data.sender_id,
            category=data.category, source="api" if principal.kind == "api_key" else "dashboard",
            idempotency_key=idempotency_key, metadata=data.metadata,
        )
        return 202, service.message_payload(msg)

    status, body, replayed = await run_idempotent(session, tenant.id, idempotency_key, data.model_dump(), action)
    headers = {"Idempotent-Replayed": "true"} if replayed else {}
    return JSONResponse(body, status_code=status, headers=headers)


@router.post("/bulk", status_code=202)
async def send_bulk(
    data: BulkIn,
    session: TenantSession,
    principal: Principal = Depends(require(P.MESSAGES_SEND)),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JSONResponse:
    if len(data.messages) > settings.bulk_max_messages:
        raise ValidationFailed(f"At most {settings.bulk_max_messages} messages per request")
    tenant = await _tenant(session, principal)

    async def action() -> tuple[int, dict[str, Any]]:
        results: list[dict[str, Any]] = []
        accepted = 0
        for idx, item in enumerate(data.messages):
            try:
                async with session.begin_nested():
                    msg = await service.create_single_message(
                        session, tenant=tenant, principal=principal, to=item.to, body=item.message,
                        sender=data.sender_id, category=data.category, source="api", metadata=item.metadata,
                        priority=False,
                    )
                results.append({"index": idx, **service.message_payload(msg)})
                accepted += 1
            except AppError as exc:
                if exc.code in ("insufficient_funds", "insufficient_demo_credits", "tenant_suspended"):
                    raise
                results.append({"index": idx, "to": item.to, "status": "rejected", "error": {"code": exc.code, "message": exc.message}})
        return 202, {"accepted": accepted, "rejected": len(data.messages) - accepted, "results": results}

    status, body, replayed = await run_idempotent(session, tenant.id, idempotency_key, data.model_dump(), action)
    return JSONResponse(body, status_code=status, headers={"Idempotent-Replayed": "true"} if replayed else {})


@router.post("/segments")
async def count_segments(data: SegmentsIn) -> dict[str, Any]:
    """Utility: encoding/segment calculation (no auth-sensitive data)."""
    info = analyze(data.message)
    return {
        "encoding": info.encoding, "length": info.length, "segments": info.segments,
        "per_segment": info.per_segment, "remaining": info.remaining, "non_gsm_chars": list(info.non_gsm_chars),
    }


@router.get("", response_model=Page[dict])
async def list_messages(
    session: TenantSession,
    principal: Principal = Depends(require(P.MESSAGES_READ)),
    params: PageParams = Depends(page_params),
    status: str | None = None,
    to: str | None = None,
    source: str | None = None,
    campaign_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> Page[dict]:
    stmt = select(Message).where(Message.tenant_id == principal.tenant_id).order_by(Message.created_at.desc())
    if status:
        stmt = stmt.where(Message.status == status)
    if to:
        stmt = stmt.where(Message.to_e164.contains(to.strip().lstrip("0")))
    if source:
        stmt = stmt.where(Message.source == source)
    if campaign_id:
        stmt = stmt.where(Message.campaign_id == campaign_id)
    if date_from:
        stmt = stmt.where(Message.created_at >= date_from)
    if date_to:
        stmt = stmt.where(Message.created_at <= date_to)
    rows, total = await paginate(session, stmt, params)
    items = []
    for m in rows:
        p = service.message_payload(m)
        p["body"] = m.body
        items.append(p)
    return Page(items=items, total=total, page=params.page, page_size=params.page_size)


@router.get("/{message_id}")
async def get_message(message_id: uuid.UUID, session: TenantSession, principal: Principal = Depends(require(P.MESSAGES_READ))) -> dict:
    m = await session.scalar(select(Message).where(Message.id == message_id, Message.tenant_id == principal.tenant_id))
    if m is None:
        raise NotFound("Message not found")
    events = (await session.scalars(
        select(MessageEvent).where(MessageEvent.message_id == m.id, MessageEvent.tenant_id == principal.tenant_id)
        .order_by(MessageEvent.occurred_at)
    )).all()
    p = service.message_payload(m)
    p["body"] = m.body
    p["error_message"] = m.error_message
    p["events"] = [{"status": e.status, "occurred_at": e.occurred_at.isoformat()} for e in events]
    return p


balance_router = APIRouter(tags=["sms"], dependencies=[RateLimit])


@balance_router.get("/balance")
async def balance(session: TenantSession, principal: Principal = Depends(require(P.BILLING_READ))) -> dict:
    from app.modules.wallet.service import available, get_wallet

    assert principal.tenant_id
    w = await get_wallet(session, principal.tenant_id)
    tenant = await session.get(Tenant, principal.tenant_id)
    return {
        "balance": float(w.balance), "reserved": float(w.reserved), "available": float(available(w)),
        "currency": w.currency, "demo_credits": w.demo_credits, "mode": tenant.mode if tenant else None,
    }

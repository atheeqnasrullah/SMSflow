from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.core.deps import Principal, TenantSession, client_ip, require
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.permissions import P
from app.modules.audit.service import record_principal
from app.modules.messaging.service import SENDER_RE
from app.modules.sender_ids.models import SenderId

router = APIRouter(prefix="/sender-ids", tags=["sender ids"])


class SenderIdIn(BaseModel):
    value: str = Field(min_length=1, max_length=15)
    purpose: str | None = Field(default=None, max_length=1000)

    @field_validator("value")
    @classmethod
    def _valid(cls, v: str) -> str:
        v = v.strip()
        if not SENDER_RE.match(v):
            raise ValueError("Alphanumeric sender IDs: max 11 characters with at least one letter; numeric: 3–15 digits")
        return v


class SenderIdOut(BaseModel):
    id: uuid.UUID
    value: str
    status: str
    purpose: str | None
    rejection_reason: str | None
    reviewed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("", response_model=list[SenderIdOut])
async def list_sender_ids(session: TenantSession, principal: Principal = Depends(require(P.CAMPAIGNS_READ))) -> list[SenderId]:
    return list((await session.scalars(
        select(SenderId).where(SenderId.tenant_id == principal.tenant_id).order_by(SenderId.created_at.desc())
    )).all())


@router.post("", response_model=SenderIdOut, status_code=201)
async def request_sender_id(data: SenderIdIn, request: Request, session: TenantSession,
                            principal: Principal = Depends(require(P.SENDER_IDS_REQUEST))) -> SenderId:
    if await session.scalar(select(SenderId.id).where(SenderId.tenant_id == principal.tenant_id, SenderId.value == data.value)):
        raise Conflict("Sender ID already requested")
    sid = SenderId(tenant_id=principal.tenant_id, value=data.value, purpose=data.purpose, requested_by=principal.user_id)
    session.add(sid)
    record_principal(session, principal, "sender_id.requested", target_type="sender_id", metadata={"value": data.value},
                     ip=client_ip(request))
    await session.commit()
    return sid


@router.delete("/{sender_id}", status_code=204)
async def delete_sender_id(sender_id: uuid.UUID, session: TenantSession, principal: Principal = Depends(require(P.SENDER_IDS_REQUEST))) -> Response:
    sid = await session.scalar(select(SenderId).where(SenderId.id == sender_id, SenderId.tenant_id == principal.tenant_id))
    if sid is None:
        raise NotFound("Sender ID not found")
    if sid.status == "approved":
        raise ValidationFailed("Approved sender IDs cannot be deleted; contact support")
    await session.delete(sid)
    await session.commit()
    return Response(status_code=204)

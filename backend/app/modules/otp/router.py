from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.deps import Principal, RateLimit, TenantSession, require
from app.core.permissions import P
from app.modules.otp import service
from app.modules.tenants.models import Tenant

router = APIRouter(prefix="/otp", tags=["otp"], dependencies=[RateLimit])


class OtpSendIn(BaseModel):
    to: str
    purpose: str = Field(default="verification", max_length=40)
    sender_id: str | None = None
    template: str | None = Field(default=None, max_length=300, description="Must contain {code}; may use {brand}, {minutes}")
    brand: str | None = Field(default=None, max_length=40)
    length: int | None = Field(default=None, ge=4, le=10)
    ttl_seconds: int | None = Field(default=None, ge=60, le=1800)


class OtpVerifyIn(BaseModel):
    to: str
    code: str = Field(min_length=4, max_length=10)
    purpose: str = "verification"
    otp_id: uuid.UUID | None = None


@router.post("/send", status_code=202)
async def send(data: OtpSendIn, session: TenantSession, principal: Principal = Depends(require(P.OTP))) -> dict:
    tenant = await session.get(Tenant, principal.tenant_id)
    assert tenant is not None
    otp, msg = await service.send_otp(
        session, tenant=tenant, principal=principal, to=data.to, purpose=data.purpose, sender=data.sender_id,
        template=data.template, brand=data.brand, length=data.length, ttl_seconds=data.ttl_seconds,
    )
    await session.commit()
    return {
        "otp_id": str(otp.id), "message_id": str(msg.id), "to": otp.to_e164, "expires_at": otp.expires_at.isoformat(),
        "status": msg.status, "is_demo": msg.is_demo,
    }


@router.post("/verify")
async def verify(data: OtpVerifyIn, session: TenantSession, principal: Principal = Depends(require(P.OTP))) -> dict:
    assert principal.tenant_id
    ok, reason = await service.verify_otp(
        session, tenant_id=principal.tenant_id, to=data.to, code=data.code, purpose=data.purpose, otp_id=data.otp_id
    )
    await session.commit()
    return {"verified": ok, "reason": reason}

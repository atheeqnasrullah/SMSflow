"""OTP: CSPRNG codes, only hashes stored, expiry, attempt limits, per-number throttling."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import utcnow
from app.core.errors import RateLimited, ValidationFailed
from app.core.security import constant_time_equals, generate_numeric_code, hash_otp
from app.modules.messaging import service as msg_service
from app.modules.messaging.models import OtpRequest
from app.modules.tenants.models import Tenant
from app.shared import phone as phone_util

DEFAULT_TEMPLATE = "Your {brand} verification code is {code}. It expires in {minutes} minutes. Do not share it."


async def send_otp(
    session: AsyncSession,
    *,
    tenant: Tenant,
    principal: Any,
    to: str,
    purpose: str,
    sender: str | None,
    template: str | None,
    brand: str | None,
    length: int | None,
    ttl_seconds: int | None,
) -> tuple[OtpRequest, Any]:
    try:
        to_e164 = phone_util.normalize(to)
    except phone_util.InvalidPhoneNumber as exc:
        raise ValidationFailed(f"Invalid phone number: {to}", code="invalid_number") from exc

    window_start = utcnow() - timedelta(minutes=10)
    recent = await session.scalar(
        select(func.count(OtpRequest.id)).where(
            OtpRequest.tenant_id == tenant.id, OtpRequest.to_e164 == to_e164, OtpRequest.created_at >= window_start
        )
    )
    if int(recent or 0) >= settings.otp_max_per_number_per_10min:
        raise RateLimited("Too many OTP requests for this number; try again later", retry_after=600)

    length = max(4, min(10, length or settings.otp_length))
    ttl = max(60, min(1800, ttl_seconds or settings.otp_ttl_seconds))
    code = generate_numeric_code(length)
    otp = OtpRequest(
        id=uuid.uuid4(), tenant_id=tenant.id, to_e164=to_e164, purpose=purpose, code_hash="",
        expires_at=utcnow() + timedelta(seconds=ttl), max_attempts=settings.otp_max_attempts,
    )
    otp.code_hash = hash_otp(code, str(otp.id))
    tpl = template or DEFAULT_TEMPLATE
    if "{code}" not in tpl:
        raise ValidationFailed("OTP template must contain {code}")
    body = tpl.replace("{code}", code).replace("{brand}", brand or tenant.name).replace("{minutes}", str(ttl // 60))
    msg = await msg_service.create_single_message(
        session, tenant=tenant, principal=principal, to=to_e164, body=body, sender=sender, category="otp",
        source="otp", priority=True, metadata={"otp_id": str(otp.id), "purpose": purpose},
    )
    otp.message_id = msg.id
    session.add(otp)
    await session.flush()
    return otp, msg


async def verify_otp(session: AsyncSession, *, tenant_id: uuid.UUID, to: str, code: str, purpose: str,
                     otp_id: uuid.UUID | None) -> tuple[bool, str]:
    to_e164 = phone_util.try_normalize(to)
    if to_e164 is None:
        return False, "invalid_number"
    stmt = (
        select(OtpRequest)
        .where(OtpRequest.tenant_id == tenant_id, OtpRequest.to_e164 == to_e164, OtpRequest.purpose == purpose,
               OtpRequest.verified_at.is_(None))
        .order_by(OtpRequest.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    if otp_id:
        stmt = stmt.where(OtpRequest.id == otp_id)
    otp = await session.scalar(stmt)
    if otp is None:
        return False, "not_found"
    if otp.expires_at < utcnow():
        return False, "expired"
    if otp.attempts >= otp.max_attempts:
        return False, "too_many_attempts"
    otp.attempts += 1
    if not constant_time_equals(otp.code_hash, hash_otp(code.strip(), str(otp.id))):
        return False, "invalid_code"
    otp.verified_at = utcnow()
    return True, "verified"

"""Registration, login (with lockout), rotating refresh tokens, verification and password reset."""

from __future__ import annotations

import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import system_session, utcnow
from app.core.errors import Conflict, Forbidden, NotFound, Unauthorized, ValidationFailed
from app.core.permissions import Role, permissions_for_role
from app.core.security import (
    create_access_token,
    hash_password,
    new_opaque_token,
    password_needs_rehash,
    sha256_hex,
    verify_password,
)
from app.modules.audit.service import record
from app.modules.auth.models import RefreshToken, User, UserToken
from app.modules.auth.schemas import MeOut, RegisterIn, WorkspaceOut
from app.modules.tenants.models import Invitation, Membership, Tenant
from app.modules.wallet.models import Wallet
from app.shared import phone as phone_util
from app.workers.dispatch import defer


@dataclass
class TokenPair:
    access_token: str
    expires_in: int
    refresh_token: str
    user: User
    tenant_id: uuid.UUID | None


_DUMMY: list[str] = []


def _dummy_hash() -> str:
    if not _DUMMY:
        _DUMMY.append(hash_password(secrets.token_hex(16)))
    return _DUMMY[0]


def slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "workspace"
    return f"{base}-{secrets.token_hex(3)}"


async def create_tenant_with_owner(
    s: AsyncSession, *, user: User, name: str, business_type: str | None
) -> Tenant:
    tenant = Tenant(name=name, slug=slugify(name), business_type=business_type, contact_email=user.email)
    s.add(tenant)
    await s.flush()
    s.add(Membership(tenant_id=tenant.id, user_id=user.id, role=Role.owner.value))
    s.add(Wallet(tenant_id=tenant.id, currency=settings.currency, demo_credits=settings.demo_signup_credits))
    await s.flush()
    return tenant


async def _issue(
    s: AsyncSession,
    user: User,
    tenant_id: uuid.UUID | None,
    *,
    ip: str | None,
    user_agent: str | None,
    family_id: uuid.UUID | None = None,
) -> TokenPair:
    role = None
    if tenant_id is not None:
        m = await s.scalar(
            select(Membership).where(
                Membership.user_id == user.id, Membership.tenant_id == tenant_id, Membership.status == "active"
            )
        )
        if m is None:
            tenant_id = None
        else:
            role = m.role
    access, ttl = create_access_token(
        user_id=user.id, tenant_id=tenant_id, role=role, is_platform_admin=user.is_platform_admin
    )
    raw = new_opaque_token()
    s.add(
        RefreshToken(
            user_id=user.id,
            token_hash=sha256_hex(raw),
            family_id=family_id or uuid.uuid4(),
            tenant_id=tenant_id,
            expires_at=utcnow() + timedelta(days=settings.refresh_token_ttl_days),
            user_agent=(user_agent or "")[:400],
            ip=ip,
        )
    )
    if tenant_id is not None:
        user.last_tenant_id = tenant_id
    return TokenPair(access, ttl, raw, user, tenant_id)


async def _default_tenant(s: AsyncSession, user: User) -> uuid.UUID | None:
    rows = (
        await s.scalars(
            select(Membership.tenant_id)
            .where(Membership.user_id == user.id, Membership.status == "active")
            .order_by(Membership.created_at)
        )
    ).all()
    if user.last_tenant_id in rows:
        return user.last_tenant_id
    return rows[0] if rows else None


async def _create_user_token(s: AsyncSession, user: User, purpose: str, ttl: timedelta) -> str:
    raw = new_opaque_token()
    s.add(UserToken(user_id=user.id, purpose=purpose, token_hash=sha256_hex(raw), expires_at=utcnow() + ttl))
    return raw


def _queue_email(s: AsyncSession, to: str, subject: str, text: str) -> None:
    defer(s, "email.send", to=to, subject=subject, text=text)


async def register(data: RegisterIn, *, ip: str | None, user_agent: str | None) -> TokenPair:
    email = data.email.lower()
    async with system_session() as s:
        if await s.scalar(select(User.id).where(User.email == email)):
            raise Conflict("An account with this email already exists", code="email_taken")
        phone = phone_util.try_normalize(data.phone) if data.phone else None
        user = User(
            email=email, password_hash=hash_password(data.password), full_name=data.full_name,
            phone_e164=phone, locale=data.locale if data.locale in ("en", "si", "ta") else "en",
        )
        s.add(user)
        await s.flush()
        tenant = await create_tenant_with_owner(s, user=user, name=data.business_name, business_type=data.business_type)
        token = await _create_user_token(s, user, "verify_email", timedelta(days=2))
        _queue_email(
            s, email, "Verify your SMSFlow account",
            f"Welcome to SMSFlow, {user.full_name}!\n\nVerify your email: "
            f"{settings.frontend_url}/verify-email?token={token}\n",
        )
        record(s, "auth.register", tenant_id=tenant.id, actor_user_id=user.id, ip=ip)
        pair = await _issue(s, user, tenant.id, ip=ip, user_agent=user_agent)
        await s.commit()
        return pair


async def login(email: str, password: str, *, ip: str | None, user_agent: str | None) -> TokenPair:
    email = email.lower()
    async with system_session() as s:
        user = await s.scalar(select(User).where(User.email == email))
        if user is None:
            verify_password(password, _dummy_hash())  # equalise timing for unknown emails
            raise Unauthorized("Invalid email or password", code="invalid_credentials")
        now = utcnow()
        if user.locked_until and user.locked_until > now:
            raise Forbidden("Account temporarily locked after too many failed attempts", code="account_locked")
        if not verify_password(password, user.password_hash):
            user.failed_login_count += 1
            if user.failed_login_count >= settings.login_max_failures:
                user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
                user.failed_login_count = 0
                record(s, "auth.lockout", actor_user_id=user.id, ip=ip)
            await s.commit()
            raise Unauthorized("Invalid email or password", code="invalid_credentials")
        if not user.is_active:
            raise Forbidden("Account disabled", code="account_disabled")
        if password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = now
        tenant_id = await _default_tenant(s, user)
        record(s, "auth.login", tenant_id=tenant_id, actor_user_id=user.id, ip=ip)
        pair = await _issue(s, user, tenant_id, ip=ip, user_agent=user_agent)
        await s.commit()
        return pair


async def refresh(raw: str | None, *, ip: str | None, user_agent: str | None) -> TokenPair:
    if not raw:
        raise Unauthorized("No refresh token", code="no_refresh_token")
    async with system_session() as s:
        token = await s.scalar(select(RefreshToken).where(RefreshToken.token_hash == sha256_hex(raw)).with_for_update())
        if token is None:
            raise Unauthorized("Invalid refresh token", code="invalid_refresh_token")
        now = utcnow()
        if token.revoked_at is not None:
            # Reuse of a rotated token → likely theft: revoke the whole family.
            await s.execute(
                update(RefreshToken)
                .where(RefreshToken.family_id == token.family_id, RefreshToken.revoked_at.is_(None))
                .values(revoked_at=now)
            )
            record(s, "auth.refresh_reuse_detected", actor_user_id=token.user_id, ip=ip)
            await s.commit()
            raise Unauthorized("Session revoked", code="refresh_reuse")
        if token.expires_at < now:
            raise Unauthorized("Session expired", code="refresh_expired")
        user = await s.get(User, token.user_id)
        if user is None or not user.is_active:
            raise Unauthorized("Account disabled")
        token.revoked_at = now
        pair = await _issue(s, user, token.tenant_id, ip=ip, user_agent=user_agent, family_id=token.family_id)
        await s.commit()
        return pair


async def logout(raw: str | None) -> None:
    if not raw:
        return
    async with system_session() as s:
        token = await s.scalar(select(RefreshToken).where(RefreshToken.token_hash == sha256_hex(raw)))
        if token:
            await s.execute(
                update(RefreshToken)
                .where(RefreshToken.family_id == token.family_id, RefreshToken.revoked_at.is_(None))
                .values(revoked_at=utcnow())
            )
            await s.commit()


async def switch_tenant(user_id: uuid.UUID, tenant_id: uuid.UUID, *, ip: str | None, user_agent: str | None) -> TokenPair:
    async with system_session() as s:
        user = await s.get(User, user_id)
        if user is None:
            raise Unauthorized("Unknown user")
        member = await s.scalar(
            select(Membership).where(
                Membership.user_id == user_id, Membership.tenant_id == tenant_id, Membership.status == "active"
            )
        )
        if member is None:
            raise Forbidden("You are not a member of that workspace")
        pair = await _issue(s, user, tenant_id, ip=ip, user_agent=user_agent)
        await s.commit()
        return pair


async def _consume_user_token(s: AsyncSession, raw: str, purpose: str) -> UserToken:
    tok = await s.scalar(
        select(UserToken).where(UserToken.token_hash == sha256_hex(raw), UserToken.purpose == purpose).with_for_update()
    )
    if tok is None or tok.used_at is not None or tok.expires_at < utcnow():
        raise ValidationFailed("Invalid or expired token", code="invalid_token")
    tok.used_at = utcnow()
    return tok


async def verify_email(raw: str) -> None:
    async with system_session() as s:
        tok = await _consume_user_token(s, raw, "verify_email")
        user = await s.get(User, tok.user_id)
        assert user is not None
        user.email_verified_at = user.email_verified_at or utcnow()
        await s.commit()


async def resend_verification(user_id: uuid.UUID) -> None:
    async with system_session() as s:
        user = await s.get(User, user_id)
        if user is None or user.email_verified_at:
            return
        token = await _create_user_token(s, user, "verify_email", timedelta(days=2))
        _queue_email(s, user.email, "Verify your SMSFlow account",
                     f"Verify your email: {settings.frontend_url}/verify-email?token={token}\n")
        await s.commit()


async def forgot_password(email: str) -> None:
    async with system_session() as s:
        user = await s.scalar(select(User).where(User.email == email.lower()))
        if user is None:
            return  # do not reveal whether the email exists
        token = await _create_user_token(s, user, "reset_password", timedelta(hours=1))
        _queue_email(s, user.email, "Reset your SMSFlow password",
                     f"Reset your password (valid for 1 hour): {settings.frontend_url}/reset-password?token={token}\n"
                     "If you did not request this, ignore this email.")
        await s.commit()


async def reset_password(raw: str, password: str, *, ip: str | None) -> None:
    async with system_session() as s:
        tok = await _consume_user_token(s, raw, "reset_password")
        user = await s.get(User, tok.user_id)
        assert user is not None
        user.password_hash = hash_password(password)
        user.failed_login_count = 0
        user.locked_until = None
        await s.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )
        record(s, "auth.password_reset", actor_user_id=user.id, ip=ip)
        await s.commit()


async def change_password(user_id: uuid.UUID, current: str, new: str, *, ip: str | None) -> None:
    async with system_session() as s:
        user = await s.get(User, user_id)
        if user is None or not verify_password(current, user.password_hash):
            raise ValidationFailed("Current password is incorrect", code="wrong_password")
        user.password_hash = hash_password(new)
        record(s, "auth.password_changed", actor_user_id=user.id, ip=ip)
        await s.commit()


async def me(user_id: uuid.UUID, tenant_id: uuid.UUID | None, role: str | None) -> MeOut:
    async with system_session() as s:
        user = await s.get(User, user_id)
        if user is None:
            raise NotFound("User not found")
        rows = (
            await s.execute(
                select(Tenant, Membership.role)
                .join(Membership, Membership.tenant_id == Tenant.id)
                .where(Membership.user_id == user_id, Membership.status == "active")
                .order_by(Tenant.name)
            )
        ).all()
        return MeOut(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            locale=user.locale,
            email_verified=user.email_verified_at is not None,
            is_platform_admin=user.is_platform_admin,
            current_tenant_id=tenant_id,
            role=role,
            permissions=sorted(permissions_for_role(role)),
            workspaces=[
                WorkspaceOut(id=t.id, name=t.name, slug=t.slug, role=r, mode=t.mode, status=t.status)
                for t, r in rows
            ],
            created_at=user.created_at,
        )


async def update_profile(user_id: uuid.UUID, *, full_name: str | None, locale: str | None, phone: str | None) -> None:
    async with system_session() as s:
        user = await s.get(User, user_id)
        if user is None:
            raise NotFound("User not found")
        if full_name:
            user.full_name = full_name
        if locale:
            user.locale = locale
        if phone is not None:
            user.phone_e164 = phone_util.try_normalize(phone) if phone else None
        await s.commit()


async def accept_invitation(
    raw: str, *, current_user_id: uuid.UUID | None, full_name: str | None, password: str | None,
    ip: str | None, user_agent: str | None,
) -> TokenPair:
    async with system_session() as s:
        inv = await s.scalar(select(Invitation).where(Invitation.token_hash == sha256_hex(raw)).with_for_update())
        now = utcnow()
        if inv is None or inv.accepted_at or inv.revoked_at or inv.expires_at < now:
            raise ValidationFailed("Invitation is invalid or expired", code="invalid_invitation")
        user = await s.scalar(select(User).where(User.email == inv.email.lower()))
        if user is None:
            if not (full_name and password):
                raise ValidationFailed("full_name and password are required to create your account",
                                       code="account_required")
            user = User(email=inv.email.lower(), password_hash=hash_password(password), full_name=full_name,
                        email_verified_at=now)  # invitation proves mailbox ownership
            s.add(user)
            await s.flush()
        elif current_user_id is not None and current_user_id != user.id:
            raise Forbidden("This invitation was sent to a different email address")
        elif current_user_id is None and not (password and verify_password(password, user.password_hash)):
            raise Unauthorized("Log in (or provide your password) to accept this invitation")
        existing = await s.scalar(
            select(Membership).where(Membership.tenant_id == inv.tenant_id, Membership.user_id == user.id)
        )
        if existing:
            existing.role = inv.role
            existing.status = "active"
        else:
            s.add(Membership(tenant_id=inv.tenant_id, user_id=user.id, role=inv.role))
        inv.accepted_at = now
        await s.flush()
        record(s, "team.invitation_accepted", tenant_id=inv.tenant_id, actor_user_id=user.id, ip=ip,
               metadata={"role": inv.role})
        pair = await _issue(s, user, inv.tenant_id, ip=ip, user_agent=user_agent)
        await s.commit()
        return pair

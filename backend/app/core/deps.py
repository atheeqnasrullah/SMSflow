"""FastAPI dependencies: principal resolution (JWT or API key), RBAC, tenant session, rate limits."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Annotated, Literal

import jwt
from fastapi import Depends, Request, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import SessionLocal, system_session, utcnow
from app.core.errors import Forbidden, RateLimited, Unauthorized
from app.core.kv import get_kv
from app.core.permissions import permissions_for_role, permissions_for_scopes
from app.core.security import api_key_prefix, decode_access_token, sha256_hex


@dataclass
class Principal:
    kind: Literal["user", "api_key"]
    tenant_id: uuid.UUID | None
    user_id: uuid.UUID | None = None
    api_key_id: uuid.UUID | None = None
    role: str | None = None
    scopes: list[str] = field(default_factory=list)
    is_platform_admin: bool = False
    is_test_key: bool = False
    permissions: frozenset[str] = frozenset()

    def can(self, permission: str) -> bool:
        return permission in self.permissions

    @property
    def actor_type(self) -> str:
        return self.kind

    @property
    def actor_id(self) -> uuid.UUID | None:
        return self.user_id or self.api_key_id

    @property
    def rate_limit_key(self) -> str:
        return f"key:{self.api_key_id}" if self.api_key_id else f"user:{self.user_id}"


def _bearer(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("x-api-key")


async def _principal_from_api_key(token: str) -> Principal:
    prefix = api_key_prefix(token)
    if not prefix:
        raise Unauthorized("Invalid API key")
    digest = sha256_hex(token)
    kv = get_kv()
    cached = await kv.get(f"apikey:{digest}")
    if cached:
        data = json.loads(cached)
    else:
        from app.modules.api_keys.models import ApiKey
        from app.modules.tenants.models import Tenant

        async with system_session() as s:
            row = (
                await s.execute(
                    select(ApiKey, Tenant.status)
                    .join(Tenant, Tenant.id == ApiKey.tenant_id)
                    .where(ApiKey.prefix == prefix)
                )
            ).first()
            if row is None:
                raise Unauthorized("Invalid API key")
            key, tenant_status = row
            if not _ct_eq(key.key_hash, digest):
                raise Unauthorized("Invalid API key")
            if key.revoked_at is not None:
                raise Unauthorized("API key revoked")
            if key.expires_at is not None and key.expires_at < utcnow():
                raise Unauthorized("API key expired")
            if tenant_status == "suspended":
                raise Forbidden("Workspace suspended", code="tenant_suspended")
            if key.last_used_at is None or key.last_used_at < utcnow() - timedelta(minutes=1):
                await s.execute(update(ApiKey).where(ApiKey.id == key.id).values(last_used_at=utcnow()))
                await s.commit()
            data = {
                "id": str(key.id),
                "tenant_id": str(key.tenant_id),
                "scopes": list(key.scopes or []),
                "test": key.prefix.startswith("sf_test_"),
            }
        await kv.set(f"apikey:{digest}", json.dumps(data), ex=60)
    scopes = data["scopes"]
    return Principal(
        kind="api_key",
        tenant_id=uuid.UUID(data["tenant_id"]),
        api_key_id=uuid.UUID(data["id"]),
        scopes=scopes,
        is_test_key=data["test"],
        permissions=permissions_for_scopes(scopes),
    )


def _ct_eq(a: str, b: str) -> bool:
    import hmac

    return hmac.compare_digest(a, b)


async def get_principal(request: Request) -> Principal:
    token = _bearer(request)
    if not token:
        raise Unauthorized("Authentication required")
    if token.startswith("sf_"):
        principal = await _principal_from_api_key(token)
    else:
        try:
            claims = decode_access_token(token)
        except jwt.ExpiredSignatureError as exc:
            raise Unauthorized("Access token expired", code="token_expired") from exc
        except jwt.InvalidTokenError as exc:
            raise Unauthorized("Invalid access token") from exc
        tid = claims.get("tid")
        role = claims.get("role")
        principal = Principal(
            kind="user",
            user_id=uuid.UUID(claims["sub"]),
            tenant_id=uuid.UUID(tid) if tid else None,
            role=role,
            is_platform_admin=bool(claims.get("pa")),
            permissions=permissions_for_role(role),
        )
    request.state.principal = principal
    import structlog

    structlog.contextvars.bind_contextvars(
        tenant_id=str(principal.tenant_id) if principal.tenant_id else None
    )
    return principal


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def require(*permissions: str) -> Callable[..., Principal]:
    async def _dep(principal: CurrentPrincipal) -> Principal:
        if principal.tenant_id is None:
            raise Forbidden("No workspace selected", code="no_tenant")
        missing = [p for p in permissions if not principal.can(p)]
        if missing:
            raise Forbidden(f"Missing permission: {', '.join(missing)}")
        return principal

    return _dep


def require_user() -> Callable[..., Principal]:
    async def _dep(principal: CurrentPrincipal) -> Principal:
        if principal.kind != "user":
            raise Forbidden("This endpoint requires a dashboard user session")
        return principal

    return _dep


async def require_platform_admin(principal: CurrentPrincipal) -> Principal:
    if principal.kind != "user" or not principal.is_platform_admin:
        raise Forbidden("Platform administrator access required")
    return principal


async def get_tenant_session(principal: CurrentPrincipal) -> AsyncIterator[AsyncSession]:
    if principal.tenant_id is None:
        raise Forbidden("No workspace selected", code="no_tenant")
    async with SessionLocal() as session:
        session.info["tenant_id"] = principal.tenant_id
        yield session


TenantSession = Annotated[AsyncSession, Depends(get_tenant_session)]


async def rate_limit(request: Request, response: Response, principal: CurrentPrincipal) -> None:
    """Fixed one-second window per principal + per tenant (Redis in production)."""
    limit = settings.rate_limit_per_second
    kv = get_kv()
    import time

    window = int(time.time())
    count = await kv.incr(f"rl:{principal.rate_limit_key}:{window}", ex=2)
    tenant_count = (
        await kv.incr(f"rl:tenant:{principal.tenant_id}:{window}", ex=2) if principal.tenant_id else 0
    )
    remaining = max(0, limit - count)
    response.headers["X-RateLimit-Limit"] = str(limit)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    if count > limit or tenant_count > limit * 5:
        raise RateLimited("Rate limit exceeded", retry_after=1)


RateLimit = Depends(rate_limit)


def client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None

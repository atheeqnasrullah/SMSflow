from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select

from app.core.db import utcnow
from app.core.deps import Principal, TenantSession, client_ip, require
from app.core.errors import NotFound, ValidationFailed
from app.core.kv import get_kv
from app.core.permissions import ALL_SCOPES, P
from app.core.security import generate_api_key
from app.modules.api_keys.models import ApiKey, ApiRequestLog
from app.modules.audit.service import record_principal
from app.modules.tenants.models import Tenant
from app.shared.pagination import Page, PageParams, page_params, paginate

router = APIRouter(prefix="/developers", tags=["developers"])


class ApiKeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(default_factory=lambda: ["sms:send", "sms:read", "otp", "balance:read"])
    test: bool = False
    expires_at: datetime | None = None

    @field_validator("scopes")
    @classmethod
    def _scopes(cls, v: list[str]) -> list[str]:
        bad = [s for s in v if s not in ALL_SCOPES]
        if bad:
            raise ValueError(f"Unknown scopes: {', '.join(bad)}")
        if not v:
            raise ValueError("At least one scope is required")
        return sorted(set(v))


class ApiKeyOut(BaseModel):
    id: uuid.UUID
    name: str
    prefix: str
    scopes: list[str]
    is_test: bool
    last_used_at: datetime | None
    revoked_at: datetime | None
    expires_at: datetime | None
    created_at: datetime


class ApiKeyCreated(ApiKeyOut):
    key: str


class RequestLogOut(BaseModel):
    id: uuid.UUID
    api_key_id: uuid.UUID | None
    method: str
    path: str
    status_code: int
    latency_ms: int
    created_at: datetime

    model_config = {"from_attributes": True}


def _out(k: ApiKey) -> ApiKeyOut:
    return ApiKeyOut(
        id=k.id, name=k.name, prefix=k.prefix, scopes=list(k.scopes or []), is_test=k.prefix.startswith("sf_test_"),
        last_used_at=k.last_used_at, revoked_at=k.revoked_at, expires_at=k.expires_at, created_at=k.created_at,
    )


@router.get("/scopes")
async def scopes() -> dict:
    return {"scopes": list(ALL_SCOPES)}


@router.get("/api-keys", response_model=list[ApiKeyOut])
async def list_keys(session: TenantSession, principal: Principal = Depends(require(P.DEVELOPERS_MANAGE))) -> list[ApiKeyOut]:
    keys = (await session.scalars(
        select(ApiKey).where(ApiKey.tenant_id == principal.tenant_id).order_by(ApiKey.created_at.desc())
    )).all()
    return [_out(k) for k in keys]


@router.post("/api-keys", response_model=ApiKeyCreated, status_code=201)
async def create_key(data: ApiKeyIn, request: Request, session: TenantSession,
                     principal: Principal = Depends(require(P.DEVELOPERS_MANAGE))) -> ApiKeyCreated:
    if principal.kind != "user":
        raise ValidationFailed("API keys can only be created from the dashboard")
    tenant = await session.get(Tenant, principal.tenant_id)
    assert tenant is not None
    live = not data.test
    if live and tenant.mode != "live":
        live = False  # demo workspaces only get test keys
    full, prefix, digest = generate_api_key(live)
    key = ApiKey(tenant_id=principal.tenant_id, name=data.name, prefix=prefix, key_hash=digest, scopes=data.scopes,
                 expires_at=data.expires_at, created_by=principal.user_id)
    session.add(key)
    record_principal(session, principal, "api_key.created", target_type="api_key", target_id=key.id,
                     metadata={"prefix": prefix, "scopes": data.scopes}, ip=client_ip(request))
    await session.commit()
    return ApiKeyCreated(**_out(key).model_dump(), key=full)


@router.delete("/api-keys/{key_id}", status_code=204)
async def revoke_key(key_id: uuid.UUID, request: Request, session: TenantSession,
                     principal: Principal = Depends(require(P.DEVELOPERS_MANAGE))) -> Response:
    key = await session.scalar(select(ApiKey).where(ApiKey.id == key_id, ApiKey.tenant_id == principal.tenant_id))
    if key is None:
        raise NotFound("API key not found")
    if key.revoked_at is None:
        key.revoked_at = utcnow()
        await get_kv().delete(f"apikey:{key.key_hash}")  # immediate revocation
        record_principal(session, principal, "api_key.revoked", target_type="api_key", target_id=key.id,
                         metadata={"prefix": key.prefix}, ip=client_ip(request))
        await session.commit()
    return Response(status_code=204)


@router.get("/request-logs", response_model=Page[RequestLogOut])
async def request_logs(session: TenantSession, principal: Principal = Depends(require(P.DEVELOPERS_MANAGE)),
                       params: PageParams = Depends(page_params), api_key_id: uuid.UUID | None = None) -> Page[RequestLogOut]:
    stmt = select(ApiRequestLog).where(ApiRequestLog.tenant_id == principal.tenant_id).order_by(ApiRequestLog.created_at.desc())
    if api_key_id:
        stmt = stmt.where(ApiRequestLog.api_key_id == api_key_id)
    rows, total = await paginate(session, stmt, params)
    return Page(items=[RequestLogOut.model_validate(r) for r in rows], total=total, page=params.page, page_size=params.page_size)


@router.get("/usage")
async def usage(session: TenantSession, principal: Principal = Depends(require(P.DEVELOPERS_MANAGE))) -> dict:
    rows = (await session.execute(
        select(ApiRequestLog.api_key_id, func.count(ApiRequestLog.id))
        .where(ApiRequestLog.tenant_id == principal.tenant_id).group_by(ApiRequestLog.api_key_id)
    )).all()
    return {"requests_by_key": {str(k): n for k, n in rows}}

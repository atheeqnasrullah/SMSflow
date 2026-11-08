from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.deps import Principal, TenantSession, client_ip, require
from app.core.errors import NotFound, ValidationFailed
from app.core.permissions import P
from app.core.security import decrypt_str, encrypt_str
from app.modules.audit.service import record_principal
from app.modules.webhooks import service
from app.modules.webhooks.models import WEBHOOK_EVENTS, WebhookDelivery, WebhookEndpoint
from app.shared.pagination import Page, PageParams, page_params, paginate
from app.workers.dispatch import defer

router = APIRouter(prefix="/developers/webhooks", tags=["developers"])


class EndpointIn(BaseModel):
    url: str = Field(max_length=500)
    events: list[str] = Field(min_length=1)
    description: str | None = Field(default=None, max_length=200)


class EndpointUpdate(BaseModel):
    url: str | None = Field(default=None, max_length=500)
    events: list[str] | None = None
    description: str | None = None
    is_active: bool | None = None


class EndpointOut(BaseModel):
    id: uuid.UUID
    url: str
    description: str | None
    events: list[str]
    is_active: bool
    consecutive_failures: int
    disabled_reason: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class EndpointCreated(EndpointOut):
    secret: str


class DeliveryOut(BaseModel):
    id: uuid.UUID
    endpoint_id: uuid.UUID
    event_type: str
    payload: dict[str, Any]
    attempt: int
    response_status: int | None
    response_body: str | None
    status: str
    next_retry_at: datetime | None
    delivered_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


async def _get(session: TenantSession, principal: Principal, endpoint_id: uuid.UUID) -> WebhookEndpoint:
    ep = await session.scalar(select(WebhookEndpoint).where(WebhookEndpoint.id == endpoint_id,
                                                            WebhookEndpoint.tenant_id == principal.tenant_id))
    if ep is None:
        raise NotFound("Webhook endpoint not found")
    return ep


@router.get("/events")
async def events() -> dict:
    return {"events": list(WEBHOOK_EVENTS)}


@router.get("", response_model=list[EndpointOut])
async def list_endpoints(session: TenantSession, principal: Principal = Depends(require(P.DEVELOPERS_MANAGE))) -> list[WebhookEndpoint]:
    return list((await session.scalars(
        select(WebhookEndpoint).where(WebhookEndpoint.tenant_id == principal.tenant_id).order_by(WebhookEndpoint.created_at)
    )).all())


@router.post("", response_model=EndpointCreated, status_code=201)
async def create_endpoint(data: EndpointIn, request: Request, session: TenantSession,
                          principal: Principal = Depends(require(P.DEVELOPERS_MANAGE))) -> EndpointCreated:
    assert principal.tenant_id
    ep, secret = await service.create_endpoint(session, principal.tenant_id, data.url, data.events, data.description)
    record_principal(session, principal, "webhook.created", target_type="webhook_endpoint", target_id=ep.id,
                     metadata={"url": data.url}, ip=client_ip(request))
    await session.commit()
    return EndpointCreated(**EndpointOut.model_validate(ep).model_dump(), secret=secret)


@router.patch("/{endpoint_id}", response_model=EndpointOut)
async def update_endpoint(endpoint_id: uuid.UUID, data: EndpointUpdate, session: TenantSession,
                          principal: Principal = Depends(require(P.DEVELOPERS_MANAGE))) -> WebhookEndpoint:
    ep = await _get(session, principal, endpoint_id)
    if data.url is not None:
        try:
            service.check_url_safe(data.url)
        except service.UnsafeUrl as exc:
            raise ValidationFailed(str(exc), code="unsafe_url") from exc
        ep.url = data.url
    if data.events is not None:
        ep.events = service.validate_events(data.events)
    if data.description is not None:
        ep.description = data.description
    if data.is_active is not None:
        ep.is_active = data.is_active
        if data.is_active:
            ep.consecutive_failures = 0
            ep.disabled_reason = None
    await session.commit()
    return ep


@router.post("/{endpoint_id}/rotate-secret")
async def rotate_secret(endpoint_id: uuid.UUID, session: TenantSession, principal: Principal = Depends(require(P.DEVELOPERS_MANAGE))) -> dict:
    ep = await _get(session, principal, endpoint_id)
    secret = service.new_secret()
    ep.secret_encrypted = encrypt_str(secret)
    await session.commit()
    return {"secret": secret}


@router.get("/{endpoint_id}/secret")
async def reveal_secret(endpoint_id: uuid.UUID, session: TenantSession, principal: Principal = Depends(require(P.DEVELOPERS_MANAGE))) -> dict:
    ep = await _get(session, principal, endpoint_id)
    return {"secret": decrypt_str(ep.secret_encrypted)}


@router.delete("/{endpoint_id}", status_code=204)
async def delete_endpoint(endpoint_id: uuid.UUID, session: TenantSession, principal: Principal = Depends(require(P.DEVELOPERS_MANAGE))) -> Response:
    ep = await _get(session, principal, endpoint_id)
    await session.delete(ep)
    await session.commit()
    return Response(status_code=204)


@router.post("/{endpoint_id}/test", status_code=202)
async def send_test(endpoint_id: uuid.UUID, session: TenantSession, principal: Principal = Depends(require(P.DEVELOPERS_MANAGE))) -> dict:
    ep = await _get(session, principal, endpoint_id)
    d = WebhookDelivery(id=uuid.uuid4(), tenant_id=ep.tenant_id, endpoint_id=ep.id, event_type="test.ping",
                        payload={"type": "test.ping", "data": {"message": "Hello from SMSFlow"}})
    d.payload["id"] = f"evt_{d.id.hex}"
    session.add(d)
    defer(session, "webhooks.deliver", delivery_id=d.id, tenant_id=ep.tenant_id)
    await session.commit()
    return {"delivery_id": str(d.id)}


@router.get("/{endpoint_id}/deliveries", response_model=Page[DeliveryOut])
async def deliveries(endpoint_id: uuid.UUID, session: TenantSession, principal: Principal = Depends(require(P.DEVELOPERS_MANAGE)),
                     params: PageParams = Depends(page_params)) -> Page[DeliveryOut]:
    await _get(session, principal, endpoint_id)
    stmt = select(WebhookDelivery).where(WebhookDelivery.endpoint_id == endpoint_id,
                                         WebhookDelivery.tenant_id == principal.tenant_id).order_by(WebhookDelivery.created_at.desc())
    rows, total = await paginate(session, stmt, params)
    return Page(items=[DeliveryOut.model_validate(r) for r in rows], total=total, page=params.page, page_size=params.page_size)


@router.post("/deliveries/{delivery_id}/resend", status_code=202)
async def resend(delivery_id: uuid.UUID, session: TenantSession, principal: Principal = Depends(require(P.DEVELOPERS_MANAGE))) -> dict:
    d = await session.scalar(select(WebhookDelivery).where(WebhookDelivery.id == delivery_id,
                                                           WebhookDelivery.tenant_id == principal.tenant_id))
    if d is None:
        raise NotFound("Delivery not found")
    copy = WebhookDelivery(id=uuid.uuid4(), tenant_id=d.tenant_id, endpoint_id=d.endpoint_id, event_type=d.event_type,
                           payload=d.payload)
    session.add(copy)
    defer(session, "webhooks.deliver", delivery_id=copy.id, tenant_id=d.tenant_id)
    await session.commit()
    return {"delivery_id": str(copy.id)}

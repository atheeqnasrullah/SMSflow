from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from dateutil.rrule import rrulestr
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.core.deps import Principal, RateLimit, TenantSession, client_ip, require
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.permissions import P
from app.modules.audit.service import record_principal
from app.modules.campaigns import service
from app.modules.campaigns.models import Campaign
from app.modules.messaging.models import Message
from app.modules.messaging.service import message_payload
from app.modules.templates.models import Template
from app.modules.tenants.models import Tenant
from app.shared.pagination import Page, PageParams, page_params, paginate

router = APIRouter(prefix="/campaigns", tags=["campaigns"], dependencies=[RateLimit])


class Audience(BaseModel):
    group_ids: list[uuid.UUID] = Field(default_factory=list)
    contact_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100_000)
    numbers: list[str] = Field(default_factory=list, max_length=100_000)
    all_contacts: bool = False


class CampaignIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=1600)
    template_id: uuid.UUID | None = None
    sender: str | None = Field(default=None, max_length=15)
    category: str = Field(default="promotional", pattern="^(transactional|promotional)$")
    audience: Audience = Field(default_factory=Audience)
    recurrence: str | None = Field(default=None, max_length=255)
    missing_variable_policy: str = Field(default="skip", pattern="^(skip|fallback)$")
    missing_variable_fallback: str = Field(default="", max_length=60)

    @field_validator("recurrence")
    @classmethod
    def _rrule(cls, v: str | None) -> str | None:
        if not v:
            return None
        try:
            rrulestr(v)
        except (ValueError, TypeError) as exc:
            raise ValueError("Invalid RRULE (e.g. 'FREQ=WEEKLY;BYDAY=MO')") from exc
        return v


class CampaignUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, max_length=1600)
    template_id: uuid.UUID | None = None
    sender: str | None = None
    category: str | None = Field(default=None, pattern="^(transactional|promotional)$")
    audience: Audience | None = None
    recurrence: str | None = None
    missing_variable_policy: str | None = Field(default=None, pattern="^(skip|fallback)$")
    missing_variable_fallback: str | None = None


class LaunchIn(BaseModel):
    scheduled_at: datetime | None = None


class CampaignOut(BaseModel):
    id: uuid.UUID
    name: str
    body: str
    template_id: uuid.UUID | None
    sender: str | None
    category: str
    audience: dict[str, Any]
    status: str
    scheduled_at: datetime | None
    recurrence: str | None
    parent_campaign_id: uuid.UUID | None
    is_demo: bool
    missing_variable_policy: str
    missing_variable_fallback: str
    estimated_recipients: int
    estimated_segments: int
    estimated_cost: float
    skipped: dict[str, Any]
    stats: dict[str, Any]
    started_at: datetime | None
    completed_at: datetime | None
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


def _out(c: Campaign) -> CampaignOut:
    return CampaignOut.model_validate(c)


async def _get(session: TenantSession, principal: Principal, campaign_id: uuid.UUID, lock: bool = False) -> Campaign:
    c = await service.get_campaign(session, campaign_id, lock=lock)
    if c.tenant_id != principal.tenant_id:
        raise NotFound("Campaign not found")
    return c


async def _tenant(session: TenantSession, principal: Principal) -> Tenant:
    t = await session.get(Tenant, principal.tenant_id)
    assert t is not None
    return t


async def _check_template(session: TenantSession, principal: Principal, template_id: uuid.UUID | None) -> None:
    if template_id and not await session.scalar(
        select(Template.id).where(Template.id == template_id, Template.tenant_id == principal.tenant_id)
    ):
        raise ValidationFailed("Template not found")


@router.get("", response_model=Page[CampaignOut])
async def list_campaigns(session: TenantSession, principal: Principal = Depends(require(P.CAMPAIGNS_READ)),
                         params: PageParams = Depends(page_params), status: str | None = None) -> Page[CampaignOut]:
    stmt = select(Campaign).where(Campaign.tenant_id == principal.tenant_id).order_by(Campaign.created_at.desc())
    if status:
        stmt = stmt.where(Campaign.status == status)
    rows, total = await paginate(session, stmt, params)
    return Page(items=[_out(r) for r in rows], total=total, page=params.page, page_size=params.page_size)


@router.post("", response_model=CampaignOut, status_code=201)
async def create_campaign(data: CampaignIn, session: TenantSession, principal: Principal = Depends(require(P.CAMPAIGNS_WRITE))) -> CampaignOut:
    await _check_template(session, principal, data.template_id)
    tenant = await _tenant(session, principal)
    payload = data.model_dump()
    payload["audience"] = data.audience.model_dump(mode="json")
    c = Campaign(tenant_id=principal.tenant_id, created_by=principal.user_id, is_demo=tenant.mode == "demo", **payload)
    session.add(c)
    await session.commit()
    return _out(c)


@router.get("/{campaign_id}", response_model=CampaignOut)
async def get_campaign(campaign_id: uuid.UUID, session: TenantSession, principal: Principal = Depends(require(P.CAMPAIGNS_READ))) -> CampaignOut:
    c = await _get(session, principal, campaign_id)
    if c.status in ("processing", "paused"):
        await service.refresh_stats(session, c)
        await session.commit()
    return _out(c)


@router.patch("/{campaign_id}", response_model=CampaignOut)
async def update_campaign(campaign_id: uuid.UUID, data: CampaignUpdate, session: TenantSession,
                          principal: Principal = Depends(require(P.CAMPAIGNS_WRITE))) -> CampaignOut:
    c = await _get(session, principal, campaign_id, lock=True)
    if c.status != "draft":
        raise Conflict("Only draft campaigns can be edited")
    changes = data.model_dump(exclude_unset=True)
    if "template_id" in changes:
        await _check_template(session, principal, changes["template_id"])
    if "recurrence" in changes and changes["recurrence"]:
        CampaignIn._rrule(changes["recurrence"])  # type: ignore[call-arg]
    if data.audience is not None:
        changes["audience"] = data.audience.model_dump(mode="json")
    for k, v in changes.items():
        setattr(c, k, v)
    await session.commit()
    return _out(c)


@router.delete("/{campaign_id}", status_code=204)
async def delete_campaign(campaign_id: uuid.UUID, session: TenantSession, principal: Principal = Depends(require(P.CAMPAIGNS_WRITE))) -> Response:
    c = await _get(session, principal, campaign_id)
    if c.status != "draft":
        raise Conflict("Only drafts can be deleted; cancel the campaign instead")
    await session.delete(c)
    await session.commit()
    return Response(status_code=204)


@router.post("/{campaign_id}/estimate")
async def estimate(campaign_id: uuid.UUID, session: TenantSession, principal: Principal = Depends(require(P.CAMPAIGNS_READ))) -> dict:
    c = await _get(session, principal, campaign_id)
    tenant = await _tenant(session, principal)
    c.is_demo = tenant.mode == "demo"
    est = await service.build_estimate(session, c, tenant)
    from app.modules.wallet.service import available, get_wallet

    wallet = await get_wallet(session, tenant.id)
    out = est.public()
    out["is_demo"] = c.is_demo
    out["available_balance"] = float(available(wallet))
    out["demo_credits"] = wallet.demo_credits
    out["sufficient"] = (wallet.demo_credits >= est.segments) if c.is_demo else (available(wallet) >= est.cost)
    out["sample"] = [{"to": r.recipient.phone, "body": r.body, "segments": r.segments} for r in est.rendered[:3]]
    await session.rollback()
    return out


@router.post("/{campaign_id}/send", response_model=CampaignOut, status_code=202)
async def send_now(campaign_id: uuid.UUID, request: Request, session: TenantSession,
                   principal: Principal = Depends(require(P.CAMPAIGNS_LAUNCH))) -> CampaignOut:
    c = await _get(session, principal, campaign_id, lock=True)
    est = await service.launch(session, c, await _tenant(session, principal))
    record_principal(session, principal, "campaign.sent", target_type="campaign", target_id=c.id,
                     metadata={"recipients": est.recipients, "cost": str(est.cost)}, ip=client_ip(request))
    await session.commit()
    return _out(c)


@router.post("/{campaign_id}/schedule", response_model=CampaignOut)
async def schedule(campaign_id: uuid.UUID, data: LaunchIn, request: Request, session: TenantSession,
                   principal: Principal = Depends(require(P.CAMPAIGNS_WRITE))) -> CampaignOut:
    if data.scheduled_at is None:
        raise ValidationFailed("scheduled_at is required")
    c = await _get(session, principal, campaign_id, lock=True)
    est = await service.launch(session, c, await _tenant(session, principal), scheduled_at=data.scheduled_at)
    record_principal(session, principal, "campaign.scheduled", target_type="campaign", target_id=c.id,
                     metadata={"scheduled_at": data.scheduled_at.isoformat(), "cost": str(est.cost)}, ip=client_ip(request))
    await session.commit()
    return _out(c)


@router.post("/{campaign_id}/unschedule", response_model=CampaignOut)
async def unschedule(campaign_id: uuid.UUID, session: TenantSession, principal: Principal = Depends(require(P.CAMPAIGNS_WRITE))) -> CampaignOut:
    c = await _get(session, principal, campaign_id, lock=True)
    await service.unschedule(session, c)
    await session.commit()
    return _out(c)


@router.post("/{campaign_id}/pause", response_model=CampaignOut)
async def pause(campaign_id: uuid.UUID, session: TenantSession, principal: Principal = Depends(require(P.CAMPAIGNS_LAUNCH))) -> CampaignOut:
    c = await _get(session, principal, campaign_id, lock=True)
    await service.pause(session, c)
    await session.commit()
    return _out(c)


@router.post("/{campaign_id}/resume", response_model=CampaignOut)
async def resume(campaign_id: uuid.UUID, session: TenantSession, principal: Principal = Depends(require(P.CAMPAIGNS_LAUNCH))) -> CampaignOut:
    c = await _get(session, principal, campaign_id, lock=True)
    await service.resume(session, c)
    await session.commit()
    return _out(c)


@router.post("/{campaign_id}/cancel", response_model=CampaignOut)
async def cancel(campaign_id: uuid.UUID, request: Request, session: TenantSession,
                 principal: Principal = Depends(require(P.CAMPAIGNS_WRITE))) -> CampaignOut:
    c = await _get(session, principal, campaign_id, lock=True)
    await service.cancel(session, c)
    record_principal(session, principal, "campaign.cancelled", target_type="campaign", target_id=c.id, ip=client_ip(request))
    await session.commit()
    return _out(c)


@router.post("/{campaign_id}/duplicate", response_model=CampaignOut, status_code=201)
async def duplicate(campaign_id: uuid.UUID, session: TenantSession, principal: Principal = Depends(require(P.CAMPAIGNS_WRITE))) -> CampaignOut:
    c = await _get(session, principal, campaign_id)
    copy = await service.duplicate(session, c, principal.user_id)
    copy.is_demo = (await _tenant(session, principal)).mode == "demo"
    await session.commit()
    return _out(copy)


@router.get("/{campaign_id}/messages", response_model=Page[dict])
async def campaign_messages(campaign_id: uuid.UUID, session: TenantSession, principal: Principal = Depends(require(P.CAMPAIGNS_READ)),
                            params: PageParams = Depends(page_params), status: str | None = None) -> Page[dict]:
    await _get(session, principal, campaign_id)
    stmt = select(Message).where(Message.tenant_id == principal.tenant_id, Message.campaign_id == campaign_id).order_by(Message.created_at)
    if status:
        stmt = stmt.where(Message.status == status)
    rows, total = await paginate(session, stmt, params)
    return Page(items=[message_payload(m) for m in rows], total=total, page=params.page, page_size=params.page_size)

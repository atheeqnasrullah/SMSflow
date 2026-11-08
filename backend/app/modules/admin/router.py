"""Super-admin console API. Runs on the system DB role; every mutating action is audit-logged."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import case, func, or_, select

from app.core.db import system_session, utcnow
from app.core.deps import Principal, client_ip, require_platform_admin
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.security import decrypt_json, encrypt_json
from app.modules.audit.models import AuditLog
from app.modules.audit.service import record
from app.modules.messaging.models import Message
from app.modules.payments.models import CreditPackage, Payment
from app.modules.providers import router as provider_router
from app.modules.providers.models import Provider
from app.modules.sender_ids.models import SenderId
from app.modules.tenants.models import SupportTicket, Tenant
from app.modules.wallet import service as wallet_service
from app.modules.wallet.models import PricingRule, Wallet
from app.shared.money import money

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_platform_admin)])

AdminP = Depends(require_platform_admin)


def _audit(s: Any, principal: Principal, action: str, request: Request, *, tenant_id: uuid.UUID | None = None,
           target_type: str | None = None, target_id: Any = None, metadata: dict | None = None) -> None:
    record(s, action, tenant_id=tenant_id, actor_user_id=principal.user_id, actor_type="admin",
           target_type=target_type, target_id=target_id, metadata=metadata, ip=client_ip(request))


# --- Platform stats --------------------------------------------------------------------------------
@router.get("/stats")
async def stats() -> dict:
    since = utcnow() - timedelta(days=1)
    async with system_session() as s:
        tenants = dict((await s.execute(select(Tenant.status, func.count(Tenant.id)).group_by(Tenant.status))).all())
        modes = dict((await s.execute(select(Tenant.mode, func.count(Tenant.id)).group_by(Tenant.mode))).all())
        msgs_24h = dict((await s.execute(
            select(Message.status, func.count(Message.id)).where(Message.created_at >= since).group_by(Message.status)
        )).all())
        revenue_30d = await s.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.status == "completed", Payment.verified_at >= utcnow() - timedelta(days=30)))
        pending_sender_ids = await s.scalar(select(func.count(SenderId.id)).where(SenderId.status == "pending"))
        open_tickets = await s.scalar(select(func.count(SupportTicket.id)).where(SupportTicket.status != "closed"))
        go_live = await s.scalar(select(func.count(Tenant.id)).where(Tenant.live_requested_at.is_not(None), Tenant.mode == "demo"))
    return {
        "tenants_by_status": tenants, "tenants_by_mode": modes, "messages_24h": msgs_24h,
        "revenue_30d": float(revenue_30d or 0), "pending_sender_ids": int(pending_sender_ids or 0),
        "open_tickets": int(open_tickets or 0), "go_live_requests": int(go_live or 0),
    }


# --- Tenants -------------------------------------------------------------------------------------------
class TenantAdminUpdate(BaseModel):
    status: str | None = Field(default=None, pattern="^(active|suspended|pending)$")
    mode: str | None = Field(default=None, pattern="^(demo|live)$")
    suspended_reason: str | None = None


class WalletAdjustIn(BaseModel):
    amount: Decimal = Field(description="Signed LKR amount")
    type: str = Field(default="adjustment", pattern="^(adjustment|bonus)$")
    reason: str = Field(min_length=3, max_length=255)
    demo_credits: int | None = Field(default=None, description="Optional: add demo segments")


@router.get("/tenants")
async def list_tenants(q: str | None = None, status: str | None = None, page: int = Query(1, ge=1),
                       page_size: int = Query(50, le=200)) -> dict:
    async with system_session() as s:
        stmt = select(Tenant, Wallet).outerjoin(Wallet, Wallet.tenant_id == Tenant.id).order_by(Tenant.created_at.desc())
        if q:
            stmt = stmt.where(or_(Tenant.name.ilike(f"%{q}%"), Tenant.slug.ilike(f"%{q}%"), Tenant.contact_email.ilike(f"%{q}%")))
        if status:
            stmt = stmt.where(Tenant.status == status)
        total = await s.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
        rows = (await s.execute(stmt.offset((page - 1) * page_size).limit(page_size))).all()
    return {
        "total": int(total or 0),
        "items": [
            {
                "id": str(t.id), "name": t.name, "slug": t.slug, "status": t.status, "mode": t.mode,
                "business_type": t.business_type, "contact_email": t.contact_email, "created_at": t.created_at.isoformat(),
                "live_requested_at": t.live_requested_at.isoformat() if t.live_requested_at else None,
                "balance": float(w.balance) if w else 0.0, "reserved": float(w.reserved) if w else 0.0,
                "demo_credits": w.demo_credits if w else 0,
            }
            for t, w in rows
        ],
    }


@router.patch("/tenants/{tenant_id}")
async def update_tenant(tenant_id: uuid.UUID, data: TenantAdminUpdate, request: Request, principal: Principal = AdminP) -> dict:
    async with system_session() as s:
        t = await s.get(Tenant, tenant_id)
        if t is None:
            raise NotFound("Tenant not found")
        changes = data.model_dump(exclude_unset=True)
        for k, v in changes.items():
            setattr(t, k, v)
        if data.status == "active":
            t.suspended_reason = None
        _audit(s, principal, "admin.tenant_updated", request, tenant_id=t.id, target_type="tenant", target_id=t.id,
               metadata={k: str(v) for k, v in changes.items()})
        await s.commit()
        return {"id": str(t.id), "status": t.status, "mode": t.mode}


@router.post("/tenants/{tenant_id}/wallet-adjustments")
async def adjust_wallet(tenant_id: uuid.UUID, data: WalletAdjustIn, request: Request, principal: Principal = AdminP) -> dict:
    async with system_session() as s:
        w = await wallet_service.get_wallet(s, tenant_id, for_update=True)
        if data.amount != 0:
            if data.amount < 0 and wallet_service.available(w) < -data.amount:
                raise ValidationFailed("Adjustment would make available balance negative")
            await wallet_service.credit(
                s, w, money(data.amount), entry_type=data.type, key=f"admin:{uuid.uuid4()}",
                reference_type="admin", reference_id=principal.user_id, description=data.reason, created_by=principal.user_id,
            )
        if data.demo_credits:
            w.demo_credits = max(0, w.demo_credits + data.demo_credits)
        _audit(s, principal, "admin.wallet_adjusted", request, tenant_id=tenant_id, target_type="wallet", target_id=w.id,
               metadata={"amount": str(data.amount), "type": data.type, "reason": data.reason, "demo_credits": data.demo_credits})
        await s.commit()
        return {"balance": float(w.balance), "reserved": float(w.reserved), "demo_credits": w.demo_credits}


# --- Sender IDs ----------------------------------------------------------------------------------------
class SenderReviewIn(BaseModel):
    approve: bool
    reason: str | None = None
    provider_ref: str | None = None


@router.get("/sender-ids")
async def list_sender_ids(status: str | None = "pending") -> list[dict]:
    async with system_session() as s:
        stmt = select(SenderId, Tenant.name).join(Tenant, Tenant.id == SenderId.tenant_id).order_by(SenderId.created_at)
        if status:
            stmt = stmt.where(SenderId.status == status)
        rows = (await s.execute(stmt)).all()
    return [
        {"id": str(sid.id), "tenant_id": str(sid.tenant_id), "tenant_name": name, "value": sid.value, "status": sid.status,
         "purpose": sid.purpose, "created_at": sid.created_at.isoformat(), "rejection_reason": sid.rejection_reason}
        for sid, name in rows
    ]


@router.post("/sender-ids/{sender_id}/review")
async def review_sender_id(sender_id: uuid.UUID, data: SenderReviewIn, request: Request, principal: Principal = AdminP) -> dict:
    async with system_session() as s:
        sid = await s.get(SenderId, sender_id)
        if sid is None:
            raise NotFound("Sender ID not found")
        sid.status = "approved" if data.approve else "rejected"
        sid.rejection_reason = None if data.approve else (data.reason or "Rejected")
        sid.provider_ref = data.provider_ref or sid.provider_ref
        sid.reviewed_by = principal.user_id
        sid.reviewed_at = utcnow()
        _audit(s, principal, "admin.sender_id_reviewed", request, tenant_id=sid.tenant_id, target_type="sender_id",
               target_id=sid.id, metadata={"value": sid.value, "status": sid.status})
        await s.commit()
        return {"id": str(sid.id), "status": sid.status}


# --- Providers -----------------------------------------------------------------------------------------
class ProviderIn(BaseModel):
    name: str
    type: str = Field(pattern="^(demo|smslenz|textlk|twilio|generic)$")
    code: str = Field(pattern="^[a-z0-9_-]{2,32}$")
    config: dict[str, Any] = Field(default_factory=dict)
    priority: int = 100
    is_active: bool = True
    cost_per_segment: Decimal = Decimal(0)
    max_tps: int = Field(default=20, ge=1, le=10_000)
    categories: str = "otp,transactional,promotional"


class ProviderUpdate(BaseModel):
    name: str | None = None
    config: dict[str, Any] | None = None
    priority: int | None = None
    is_active: bool | None = None
    cost_per_segment: Decimal | None = None
    max_tps: int | None = None
    categories: str | None = None


def _provider_out(p: Provider) -> dict:
    cfg = decrypt_json(p.config_encrypted)
    redacted = {k: ("••••" if any(x in k for x in ("token", "secret", "key", "password")) else v) for k, v in cfg.items()}
    return {"id": str(p.id), "name": p.name, "type": p.type, "code": p.code, "priority": p.priority, "is_active": p.is_active,
            "cost_per_segment": float(p.cost_per_segment), "max_tps": p.max_tps, "categories": p.categories, "config": redacted}


@router.get("/providers")
async def list_providers() -> list[dict]:
    async with system_session() as s:
        rows = (await s.scalars(select(Provider).order_by(Provider.priority))).all()
        out = []
        for p in rows:
            item = _provider_out(p)
            item["healthy"] = await provider_router.is_healthy(p.code)
            out.append(item)
        return out


@router.post("/providers", status_code=201)
async def create_provider(data: ProviderIn, request: Request, principal: Principal = AdminP) -> dict:
    async with system_session() as s:
        if await s.scalar(select(Provider.id).where(Provider.code == data.code)):
            raise Conflict("Provider code already exists")
        p = Provider(name=data.name, type=data.type, code=data.code, config_encrypted=encrypt_json(data.config),
                     priority=data.priority, is_active=data.is_active, cost_per_segment=data.cost_per_segment,
                     max_tps=data.max_tps, categories=data.categories)
        s.add(p)
        _audit(s, principal, "admin.provider_created", request, target_type="provider", target_id=data.code)
        await s.commit()
        return _provider_out(p)


@router.patch("/providers/{provider_id}")
async def update_provider(provider_id: uuid.UUID, data: ProviderUpdate, request: Request, principal: Principal = AdminP) -> dict:
    async with system_session() as s:
        p = await s.get(Provider, provider_id)
        if p is None:
            raise NotFound("Provider not found")
        changes = data.model_dump(exclude_unset=True)
        if "config" in changes:
            merged = {**decrypt_json(p.config_encrypted), **{k: v for k, v in (data.config or {}).items() if v != "••••"}}
            p.config_encrypted = encrypt_json(merged)
            changes.pop("config")
        for k, v in changes.items():
            setattr(p, k, v)
        _audit(s, principal, "admin.provider_updated", request, target_type="provider", target_id=p.code,
               metadata={k: str(v) for k, v in changes.items()})
        await s.commit()
        return _provider_out(p)


@router.get("/providers/{provider_id}/balance")
async def provider_balance(provider_id: uuid.UUID) -> dict:
    async with system_session() as s:
        p = await s.get(Provider, provider_id)
        if p is None:
            raise NotFound("Provider not found")
        adapter = provider_router.build_adapter(p)
    bal = await adapter.get_balance()
    return {"amount": float(bal.amount) if bal.amount is not None else None, "currency": bal.currency}


# --- Packages & pricing ----------------------------------------------------------------------------------
class PackageIn(BaseModel):
    name: str
    description: str | None = None
    price_lkr: Decimal = Field(gt=0)
    credits: Decimal = Field(gt=0)
    bonus_credits: Decimal = Decimal(0)
    is_active: bool = True
    sort_order: int = 0


@router.get("/packages")
async def list_packages() -> list[dict]:
    async with system_session() as s:
        rows = (await s.scalars(select(CreditPackage).order_by(CreditPackage.sort_order))).all()
    return [{"id": str(p.id), "name": p.name, "description": p.description, "price_lkr": float(p.price_lkr),
             "credits": float(p.credits), "bonus_credits": float(p.bonus_credits), "is_active": p.is_active,
             "sort_order": p.sort_order} for p in rows]


@router.post("/packages", status_code=201)
async def create_package(data: PackageIn, request: Request, principal: Principal = AdminP) -> dict:
    async with system_session() as s:
        p = CreditPackage(**data.model_dump())
        s.add(p)
        _audit(s, principal, "admin.package_created", request, target_type="credit_package", metadata={"name": data.name})
        await s.commit()
        return {"id": str(p.id)}


@router.put("/packages/{package_id}")
async def update_package(package_id: uuid.UUID, data: PackageIn, request: Request, principal: Principal = AdminP) -> dict:
    async with system_session() as s:
        p = await s.get(CreditPackage, package_id)
        if p is None:
            raise NotFound("Package not found")
        for k, v in data.model_dump().items():
            setattr(p, k, v)
        _audit(s, principal, "admin.package_updated", request, target_type="credit_package", target_id=p.id)
        await s.commit()
        return {"id": str(p.id)}


class PricingIn(BaseModel):
    tenant_id: uuid.UUID | None = None
    message_category: str | None = Field(default=None, pattern="^(otp|transactional|promotional)$")
    price_per_segment: Decimal = Field(gt=0)
    effective_from: datetime | None = None


@router.get("/pricing")
async def list_pricing() -> list[dict]:
    async with system_session() as s:
        rows = (await s.scalars(select(PricingRule).order_by(PricingRule.effective_from.desc()))).all()
    return [{"id": str(r.id), "tenant_id": str(r.tenant_id) if r.tenant_id else None, "message_category": r.message_category,
             "price_per_segment": float(r.price_per_segment), "effective_from": r.effective_from.isoformat()} for r in rows]


@router.post("/pricing", status_code=201)
async def create_pricing(data: PricingIn, request: Request, principal: Principal = AdminP) -> dict:
    async with system_session() as s:
        r = PricingRule(tenant_id=data.tenant_id, message_category=data.message_category,
                        price_per_segment=data.price_per_segment, effective_from=data.effective_from or utcnow())
        s.add(r)
        _audit(s, principal, "admin.pricing_created", request, tenant_id=data.tenant_id, target_type="pricing_rule",
               metadata={"price": str(data.price_per_segment), "category": data.message_category})
        await s.commit()
        return {"id": str(r.id)}


# --- Revenue, abuse, tickets, audit ------------------------------------------------------------------------
@router.get("/revenue")
async def revenue(days: int = Query(90, ge=1, le=730)) -> dict:
    since = utcnow() - timedelta(days=days)
    day = func.date(Payment.verified_at)
    async with system_session() as s:
        rows = (await s.execute(
            select(day, func.sum(Payment.amount), func.count(Payment.id))
            .where(Payment.status == "completed", Payment.verified_at >= since).group_by(day).order_by(day)
        )).all()
        msg_cost = (await s.execute(
            select(func.coalesce(func.sum(Message.cost), 0), func.coalesce(func.sum(Message.segments), 0))
            .where(Message.charged.is_(True), Message.created_at >= since)
        )).one()
    return {
        "daily": [{"date": str(d), "amount": float(a or 0), "payments": int(n)} for d, a, n in rows],
        "total": float(sum((a or 0) for _, a, _ in rows)),
        "billed_usage": float(msg_cost[0]),
        "billed_segments": int(msg_cost[1]),
    }


@router.get("/abuse")
async def abuse(hours: int = Query(24, ge=1, le=168)) -> list[dict]:
    """Tenants ranked by volume and failure rate in the window (sudden-volume / pumping signals)."""
    since = utcnow() - timedelta(hours=hours)
    async with system_session() as s:
        rows = (await s.execute(
            select(
                Message.tenant_id, Tenant.name, func.count(Message.id),
                func.sum(case((Message.status.in_(("failed", "undelivered", "rejected")), 1), else_=0)),
                func.sum(case((Message.source == "otp", 1), else_=0)),
            )
            .join(Tenant, Tenant.id == Message.tenant_id)
            .where(Message.created_at >= since)
            .group_by(Message.tenant_id, Tenant.name)
            .order_by(func.count(Message.id).desc())
            .limit(50)
        )).all()
    return [
        {"tenant_id": str(tid), "tenant_name": name, "messages": int(n), "failed": int(f or 0), "otp": int(o or 0),
         "failure_rate": round(int(f or 0) / int(n) * 100, 2) if n else 0.0}
        for tid, name, n, f, o in rows
    ]


class TicketUpdate(BaseModel):
    status: str | None = Field(default=None, pattern="^(open|pending|closed)$")
    priority: str | None = Field(default=None, pattern="^(low|normal|high)$")
    admin_notes: str | None = None
    assign_to_me: bool = False


@router.get("/tickets")
async def list_tickets(status: str | None = None) -> list[dict]:
    async with system_session() as s:
        stmt = select(SupportTicket, Tenant.name).join(Tenant, Tenant.id == SupportTicket.tenant_id).order_by(SupportTicket.created_at.desc())
        if status:
            stmt = stmt.where(SupportTicket.status == status)
        rows = (await s.execute(stmt.limit(500))).all()
    return [{"id": str(t.id), "tenant_id": str(t.tenant_id), "tenant_name": name, "subject": t.subject, "body": t.body,
             "status": t.status, "priority": t.priority, "admin_notes": t.admin_notes,
             "assigned_to": str(t.assigned_to) if t.assigned_to else None, "created_at": t.created_at.isoformat()}
            for t, name in rows]


@router.patch("/tickets/{ticket_id}")
async def update_ticket(ticket_id: uuid.UUID, data: TicketUpdate, principal: Principal = AdminP) -> dict:
    async with system_session() as s:
        t = await s.get(SupportTicket, ticket_id)
        if t is None:
            raise NotFound("Ticket not found")
        for k in ("status", "priority", "admin_notes"):
            v = getattr(data, k)
            if v is not None:
                setattr(t, k, v)
        if data.assign_to_me:
            t.assigned_to = principal.user_id
        await s.commit()
        return {"id": str(t.id), "status": t.status}


@router.get("/audit-logs")
async def audit_logs(tenant_id: uuid.UUID | None = None, action: str | None = None, limit: int = Query(200, le=1000)) -> list[dict]:
    async with system_session() as s:
        stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
        if tenant_id:
            stmt = stmt.where(AuditLog.tenant_id == tenant_id)
        if action:
            stmt = stmt.where(AuditLog.action.ilike(f"{action}%"))
        rows = (await s.scalars(stmt)).all()
    return [{"id": str(a.id), "tenant_id": str(a.tenant_id) if a.tenant_id else None, "actor_user_id": str(a.actor_user_id) if a.actor_user_id else None,
             "actor_type": a.actor_type, "action": a.action, "target_type": a.target_type, "target_id": a.target_id,
             "metadata": a.metadata_, "ip": a.ip, "created_at": a.created_at.isoformat()} for a in rows]

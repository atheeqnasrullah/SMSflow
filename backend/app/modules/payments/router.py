"""Billing API: wallet, ledger, packages, checkout, payments, invoices + PayHere notify callback."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.config import settings
from app.core.deps import Principal, TenantSession, client_ip, require
from app.core.errors import Forbidden, NotFound
from app.core.permissions import P
from app.modules.auth.models import User
from app.modules.payments import service
from app.modules.payments.models import CreditPackage, Invoice, Payment
from app.modules.tenants.models import Tenant
from app.modules.wallet import service as wallet_service
from app.modules.wallet.models import LedgerEntry
from app.shared.pagination import Page, PageParams, page_params, paginate

router = APIRouter(prefix="/billing", tags=["billing"])
callbacks = APIRouter(prefix="/callbacks", tags=["callbacks"])


class WalletOut(BaseModel):
    balance: float
    reserved: float
    available: float
    currency: str
    demo_credits: int
    low_balance_threshold: float
    mode: str
    price_per_segment: float


class ThresholdIn(BaseModel):
    low_balance_threshold: Decimal = Field(ge=0, le=10_000_000)


class PackageOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    price_lkr: float
    credits: float
    bonus_credits: float

    model_config = {"from_attributes": True}


class LedgerOut(BaseModel):
    id: uuid.UUID
    type: str
    amount: float
    reserved_delta: float
    balance_after: float
    reserved_after: float
    reference_type: str | None
    reference_id: str | None
    description: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PaymentOut(BaseModel):
    id: uuid.UUID
    order_id: str
    amount: float
    credits: float
    bonus_credits: float
    currency: str
    status: str
    gateway: str
    verified_at: datetime | None
    created_at: datetime
    invoice_id: uuid.UUID | None = None
    invoice_number: str | None = None


class CheckoutIn(BaseModel):
    package_id: uuid.UUID


@router.get("/wallet", response_model=WalletOut)
async def wallet(session: TenantSession, principal: Principal = Depends(require(P.BILLING_READ))) -> WalletOut:
    assert principal.tenant_id
    w = await wallet_service.get_wallet(session, principal.tenant_id)
    tenant = await session.get(Tenant, principal.tenant_id)
    price = await wallet_service.price_per_segment(session, principal.tenant_id, "promotional")
    return WalletOut(
        balance=float(w.balance), reserved=float(w.reserved), available=float(wallet_service.available(w)),
        currency=w.currency, demo_credits=w.demo_credits, low_balance_threshold=float(w.low_balance_threshold),
        mode=tenant.mode if tenant else "demo", price_per_segment=float(price),
    )


@router.patch("/wallet", response_model=WalletOut)
async def update_wallet(data: ThresholdIn, session: TenantSession, principal: Principal = Depends(require(P.BILLING_MANAGE))) -> WalletOut:
    assert principal.tenant_id
    w = await wallet_service.get_wallet(session, principal.tenant_id, for_update=True)
    w.low_balance_threshold = data.low_balance_threshold
    await session.commit()
    return await wallet(session, principal)


@router.get("/ledger", response_model=Page[LedgerOut])
async def ledger(session: TenantSession, principal: Principal = Depends(require(P.BILLING_READ)),
                 params: PageParams = Depends(page_params), type: str | None = None) -> Page[LedgerOut]:
    stmt = select(LedgerEntry).where(LedgerEntry.tenant_id == principal.tenant_id).order_by(LedgerEntry.created_at.desc())
    if type:
        stmt = stmt.where(LedgerEntry.type == type)
    rows, total = await paginate(session, stmt, params)
    return Page(items=[LedgerOut.model_validate(r) for r in rows], total=total, page=params.page, page_size=params.page_size)


@router.get("/packages", response_model=list[PackageOut])
async def packages(session: TenantSession, principal: Principal = Depends(require(P.BILLING_READ))) -> list[CreditPackage]:
    return list((await session.scalars(
        select(CreditPackage).where(CreditPackage.is_active.is_(True)).order_by(CreditPackage.sort_order, CreditPackage.price_lkr)
    )).all())


@router.post("/checkout")
async def checkout(data: CheckoutIn, session: TenantSession, principal: Principal = Depends(require(P.BILLING_MANAGE))) -> dict:
    tenant = await session.get(Tenant, principal.tenant_id)
    assert tenant is not None
    user = await session.get(User, principal.user_id) if principal.user_id else None
    payment, params = await service.create_checkout(session, tenant=tenant, user=user, package_id=data.package_id)
    await session.commit()
    return {"payment_id": str(payment.id), "order_id": payment.order_id, "checkout": params}


async def _payment_out(session: TenantSession, p: Payment) -> PaymentOut:
    inv = await session.scalar(select(Invoice).where(Invoice.payment_id == p.id))
    return PaymentOut(
        id=p.id, order_id=p.order_id, amount=float(p.amount), credits=float(p.credits), bonus_credits=float(p.bonus_credits),
        currency=p.currency, status=p.status, gateway=p.gateway, verified_at=p.verified_at, created_at=p.created_at,
        invoice_id=inv.id if inv else None, invoice_number=inv.number if inv else None,
    )


@router.get("/payments", response_model=Page[PaymentOut])
async def list_payments(session: TenantSession, principal: Principal = Depends(require(P.BILLING_READ)),
                        params: PageParams = Depends(page_params)) -> Page[PaymentOut]:
    stmt = select(Payment).where(Payment.tenant_id == principal.tenant_id).order_by(Payment.created_at.desc())
    rows, total = await paginate(session, stmt, params)
    return Page(items=[await _payment_out(session, p) for p in rows], total=total, page=params.page, page_size=params.page_size)


@router.get("/payments/{order_id}", response_model=PaymentOut)
async def get_payment(order_id: str, session: TenantSession, principal: Principal = Depends(require(P.BILLING_READ))) -> PaymentOut:
    """Display-only status for the return URL. The wallet is credited only by the verified notification."""
    p = await session.scalar(select(Payment).where(Payment.order_id == order_id, Payment.tenant_id == principal.tenant_id))
    if p is None:
        raise NotFound("Payment not found")
    return await _payment_out(session, p)


@router.post("/payments/{order_id}/simulate", response_model=PaymentOut)
async def simulate_payment(order_id: str, session: TenantSession, principal: Principal = Depends(require(P.BILLING_MANAGE))) -> PaymentOut:
    """Development only: pushes a correctly signed success notification through the real verification path."""
    if settings.is_production or not settings.allow_payment_simulation:
        raise Forbidden("Payment simulation is disabled")
    p = await session.scalar(select(Payment).where(Payment.order_id == order_id, Payment.tenant_id == principal.tenant_id))
    if p is None:
        raise NotFound("Payment not found")
    form = service.build_simulated_notification(p)
    if service.payhere_configured():
        await service.handle_payhere_notify(form)
    else:
        await service.complete_payment(order_id, gateway_payment_id=form["payment_id"], raw=form,
                                       amount=form["payhere_amount"], currency=form["payhere_currency"])
    session.expire_all()
    p = await session.scalar(select(Payment).where(Payment.order_id == order_id))
    assert p is not None
    return await _payment_out(session, p)


@router.get("/invoices/{invoice_id}", response_class=HTMLResponse)
async def invoice(invoice_id: uuid.UUID, session: TenantSession, principal: Principal = Depends(require(P.BILLING_READ))) -> HTMLResponse:
    inv = await session.scalar(select(Invoice).where(Invoice.id == invoice_id, Invoice.tenant_id == principal.tenant_id))
    if inv is None:
        raise NotFound("Invoice not found")
    payment = await session.get(Payment, inv.payment_id)
    tenant = await session.get(Tenant, principal.tenant_id)
    assert payment and tenant
    return HTMLResponse(service.invoice_html(inv, payment, tenant))


@callbacks.post("/payhere/notify", response_class=PlainTextResponse, include_in_schema=False)
async def payhere_notify(request: Request) -> Response:
    form = {k: str(v) for k, v in (await request.form()).items()}
    result = await service.handle_payhere_notify(form)
    import structlog

    structlog.get_logger("smsflow.payments").info("payhere_notify", result=result, order_id=form.get("order_id"),
                                                  ip=client_ip(request))
    # Always 200 so PayHere does not hammer retries for permanently invalid payloads.
    return PlainTextResponse("OK")

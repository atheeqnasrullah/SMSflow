"""Credit packages, PayHere checkout and verified server-to-server notifications."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import system_session, utcnow
from app.core.errors import NotFound
from app.modules.audit.service import record
from app.modules.auth.models import User
from app.modules.payments.models import CreditPackage, Invoice, Payment
from app.modules.tenants.models import Tenant
from app.modules.wallet import service as wallet_service
from app.shared.money import money, money2
from app.workers.dispatch import defer

log = structlog.get_logger("smsflow.payments")


def _md5_upper(value: str) -> str:
    return hashlib.md5(value.encode()).hexdigest().upper()  # noqa: S324 - mandated by PayHere


def checkout_hash(merchant_id: str, order_id: str, amount: Decimal, currency: str, secret: str) -> str:
    return _md5_upper(f"{merchant_id}{order_id}{money2(amount):.2f}{currency}{_md5_upper(secret)}")


def notify_signature(merchant_id: str, order_id: str, amount: str, currency: str, status_code: str, secret: str) -> str:
    return _md5_upper(f"{merchant_id}{order_id}{amount}{currency}{status_code}{_md5_upper(secret)}")


def payhere_configured() -> bool:
    return bool(settings.payhere_merchant_id and settings.payhere_merchant_secret)


async def create_checkout(
    session: AsyncSession, *, tenant: Tenant, user: User | None, package_id: uuid.UUID
) -> tuple[Payment, dict[str, Any]]:
    pkg = await session.get(CreditPackage, package_id)
    if pkg is None or not pkg.is_active:
        raise NotFound("Credit package not found")
    order_id = f"SF{utcnow():%y%m%d}{secrets.token_hex(5).upper()}"
    payment = Payment(
        tenant_id=tenant.id, package_id=pkg.id, order_id=order_id, amount=money(pkg.price_lkr),
        credits=money(pkg.credits), bonus_credits=money(pkg.bonus_credits), currency="LKR",
        created_by=user.id if user else None,
    )
    session.add(payment)
    await session.flush()
    params: dict[str, Any] = {
        "action": settings.payhere_checkout_url,
        "merchant_id": settings.payhere_merchant_id or "",
        "return_url": f"{settings.frontend_url}/billing?order_id={order_id}",
        "cancel_url": f"{settings.frontend_url}/billing?cancelled={order_id}",
        "notify_url": f"{settings.api_public_url}{settings.api_prefix}/callbacks/payhere/notify",
        "order_id": order_id,
        "items": f"SMSFlow credits – {pkg.name}",
        "currency": "LKR",
        "amount": f"{money2(pkg.price_lkr):.2f}",
        "first_name": (user.full_name.split(" ")[0] if user else tenant.name)[:50],
        "last_name": (" ".join(user.full_name.split(" ")[1:]) if user else "")[:50] or "-",
        "email": user.email if user else (tenant.contact_email or ""),
        "phone": (user.phone_e164 if user else tenant.contact_phone) or "",
        "address": tenant.address or "N/A",
        "city": "Colombo",
        "country": "Sri Lanka",
        "configured": payhere_configured(),
        "simulation_available": settings.allow_payment_simulation and not settings.is_production,
    }
    if payhere_configured():
        params["hash"] = checkout_hash(
            settings.payhere_merchant_id or "", order_id, pkg.price_lkr, "LKR", settings.payhere_merchant_secret or ""
        )
    return payment, params


async def _next_invoice_number(session: AsyncSession) -> tuple[int, str]:
    seq = int((await session.scalar(select(func.max(Invoice.sequence)))) or 0) + 1
    return seq, f"INV-{utcnow():%Y}-{seq:06d}"


async def complete_payment(order_id: str, *, gateway_payment_id: str | None, raw: dict[str, Any], amount: str,
                           currency: str) -> Payment | None:
    """Idempotently mark a payment complete and credit the wallet. Only call after verification."""
    async with system_session() as s:
        payment = await s.scalar(select(Payment).where(Payment.order_id == order_id).with_for_update())
        if payment is None:
            log.warning("payhere_unknown_order", order_id=order_id)
            return None
        if payment.status == "completed":
            return payment  # duplicate notification → no-op
        if currency != payment.currency or money(amount) != money(payment.amount):
            payment.status = "failed"
            payment.raw_notification = raw
            record(s, "payment.amount_mismatch", tenant_id=payment.tenant_id, actor_type="system",
                   target_type="payment", target_id=payment.id, metadata={"amount": amount, "currency": currency})
            await s.commit()
            return payment
        payment.status = "completed"
        payment.gateway_payment_id = gateway_payment_id
        payment.raw_notification = raw
        payment.verified_at = utcnow()
        s.info["tenant_id"] = payment.tenant_id
        wallet = await wallet_service.get_wallet(s, payment.tenant_id, for_update=True)
        await wallet_service.credit(
            s, wallet, payment.credits, entry_type="topup", key=f"topup:payment:{payment.id}",
            reference_type="payment", reference_id=payment.id, description=f"Top-up {payment.order_id}",
        )
        if money(payment.bonus_credits) > 0:
            await wallet_service.credit(
                s, wallet, payment.bonus_credits, entry_type="bonus", key=f"bonus:payment:{payment.id}",
                reference_type="payment", reference_id=payment.id, description="Package bonus",
            )
        wallet.low_balance_notified_at = None
        seq, number = await _next_invoice_number(s)
        s.add(Invoice(tenant_id=payment.tenant_id, payment_id=payment.id, number=number, sequence=seq,
                      amount=payment.amount, currency=payment.currency, issued_at=utcnow()))
        record(s, "payment.completed", tenant_id=payment.tenant_id, actor_type="system", target_type="payment",
               target_id=payment.id, metadata={"amount": str(payment.amount), "order_id": order_id})
        from app.modules.webhooks.service import emit

        await emit(s, payment.tenant_id, "payment.completed", {
            "order_id": order_id, "amount": float(payment.amount), "credits": float(payment.credits),
            "bonus_credits": float(payment.bonus_credits), "currency": payment.currency,
        })
        defer(s, "payments.send_receipt", payment_id=payment.id)
        await s.commit()
        return payment


async def handle_payhere_notify(form: dict[str, str]) -> str:
    """Verify md5sig + merchant and apply. Returns a short result code for logging."""
    if not payhere_configured():
        return "not_configured"
    required = ("merchant_id", "order_id", "payhere_amount", "payhere_currency", "status_code", "md5sig")
    if any(k not in form for k in required):
        return "missing_fields"
    if form["merchant_id"] != settings.payhere_merchant_id:
        return "wrong_merchant"
    expected = notify_signature(
        form["merchant_id"], form["order_id"], form["payhere_amount"], form["payhere_currency"], form["status_code"],
        settings.payhere_merchant_secret or "",
    )
    import hmac

    if not hmac.compare_digest(expected, form["md5sig"].upper()):
        log.warning("payhere_bad_signature", order_id=form.get("order_id"))
        return "bad_signature"
    status = form["status_code"]
    if status == "2":
        await complete_payment(form["order_id"], gateway_payment_id=form.get("payment_id"), raw=form,
                               amount=form["payhere_amount"], currency=form["payhere_currency"])
        return "completed"
    new_status = {"0": "pending", "-1": "cancelled", "-2": "failed", "-3": "failed"}.get(status, "failed")
    async with system_session() as s:
        await s.execute(
            update(Payment).where(Payment.order_id == form["order_id"], Payment.status == "pending")
            .values(status=new_status, raw_notification=form)
        )
        await s.commit()
    return new_status


def build_simulated_notification(payment: Payment) -> dict[str, str]:
    """Dev only: a notification identical to what PayHere would send (signed with our secret)."""
    secret = settings.payhere_merchant_secret or "dev-secret"
    merchant = settings.payhere_merchant_id or "dev-merchant"
    amount = f"{money2(payment.amount):.2f}"
    return {
        "merchant_id": merchant, "order_id": payment.order_id, "payment_id": f"SIM{secrets.token_hex(6)}",
        "payhere_amount": amount, "payhere_currency": payment.currency, "status_code": "2",
        "md5sig": notify_signature(merchant, payment.order_id, amount, payment.currency, "2", secret),
        "method": "TEST", "status_message": "Simulated success",
    }


async def expire_stale() -> int:
    async with system_session() as s:
        res = await s.execute(
            update(Payment).where(Payment.status == "pending", Payment.created_at < utcnow() - timedelta(days=1))
            .values(status="expired")
        )
        await s.commit()
        return int(res.rowcount or 0)


def invoice_html(invoice: Invoice, payment: Payment, tenant: Tenant) -> str:
    from html import escape

    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{escape(invoice.number)}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:720px;margin:40px auto;color:#111}}
table{{width:100%;border-collapse:collapse}}td,th{{padding:8px;border-bottom:1px solid #ddd;text-align:left}}
.r{{text-align:right}}h1{{margin:0}}.muted{{color:#666}}</style></head><body>
<h1>SMSFlow</h1><p class="muted">Receipt / Invoice</p>
<p><strong>Invoice:</strong> {escape(invoice.number)}<br><strong>Date:</strong> {invoice.issued_at:%Y-%m-%d}<br>
<strong>Order:</strong> {escape(payment.order_id)}<br><strong>Billed to:</strong> {escape(tenant.name)}</p>
<table><tr><th>Description</th><th class="r">Amount ({escape(invoice.currency)})</th></tr>
<tr><td>SMS credits ({money2(payment.credits)} LKR{f" + {money2(payment.bonus_credits)} bonus" if payment.bonus_credits else ""})</td>
<td class="r">{money2(invoice.amount)}</td></tr>
<tr><th>Total paid</th><th class="r">{money2(invoice.amount)}</th></tr></table>
<p class="muted">Paid via {escape(payment.gateway)} · Payment ref {escape(payment.gateway_payment_id or "-")}</p>
</body></html>"""

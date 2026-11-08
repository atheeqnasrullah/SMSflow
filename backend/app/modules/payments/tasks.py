from __future__ import annotations

import uuid

from sqlalchemy import select

from app.core.db import system_session
from app.modules.auth.models import User
from app.modules.payments import service
from app.modules.payments.models import Invoice, Payment
from app.modules.tenants.models import Membership, Tenant
from app.shared import storage
from app.shared.email import send_email
from app.workers.registry import task


@task("payments.send_receipt", queue="default")
async def send_receipt(payment_id: str) -> None:
    async with system_session() as s:
        payment = await s.get(Payment, uuid.UUID(payment_id))
        if payment is None:
            return
        invoice = await s.scalar(select(Invoice).where(Invoice.payment_id == payment.id))
        tenant = await s.get(Tenant, payment.tenant_id)
        if invoice is None or tenant is None:
            return
        html = service.invoice_html(invoice, payment, tenant)
        if not invoice.pdf_key:
            invoice.pdf_key = storage.put_bytes(f"invoices/{tenant.id}", f"{invoice.number}.html", html.encode())
            await s.commit()
        owner_email = await s.scalar(
            select(User.email).join(Membership, Membership.user_id == User.id)
            .where(Membership.tenant_id == tenant.id, Membership.role == "owner")
        )
    if owner_email:
        await send_email(owner_email, f"SMSFlow receipt {invoice.number}",
                         f"Thank you! Your payment {payment.order_id} of LKR {payment.amount} was received.", html)


@task("payments.expire_stale", queue="default")
async def expire_stale() -> None:
    await service.expire_stale()

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select

from app.core.db import system_session
from app.modules.auth.models import User
from app.modules.tenants.models import Membership, Tenant
from app.modules.wallet import service
from app.modules.wallet.models import Wallet
from app.shared.email import send_email
from app.workers.registry import task

log = structlog.get_logger("smsflow.wallet")


@task("wallet.reconcile_all", queue="default")
async def reconcile_all() -> None:
    """Nightly: cached wallet values must equal ledger sums; alert on mismatch."""
    async with system_session() as s:
        wallets = (await s.scalars(select(Wallet))).all()
        for w in wallets:
            r = await service.reconcile(s, w)
            if r["balance_diff"] != 0 or r["reserved_diff"] != 0:
                log.error("wallet_reconciliation_mismatch", tenant_id=str(w.tenant_id),
                          **{k: str(v) for k, v in r.items()})


@task("wallet.notify_low_balance", queue="default")
async def notify_low_balance(tenant_id: str) -> None:
    async with system_session() as s:
        tenant = await s.get(Tenant, uuid.UUID(tenant_id))
        wallet = await s.scalar(select(Wallet).where(Wallet.tenant_id == uuid.UUID(tenant_id)))
        emails = (await s.scalars(
            select(User.email).join(Membership, Membership.user_id == User.id)
            .where(Membership.tenant_id == uuid.UUID(tenant_id), Membership.role.in_(("owner", "admin")))
        )).all()
    if tenant is None or wallet is None:
        return
    for email in emails:
        await send_email(
            email, "SMSFlow: low balance",
            f"Your SMSFlow workspace '{tenant.name}' has LKR {service.available(wallet)} available, below your "
            f"threshold of LKR {wallet.low_balance_threshold}. Top up to keep messages flowing.",
        )

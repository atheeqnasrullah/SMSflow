"""Wallet ledger: append-only entries, cached balance/reserved updated in the same transaction.

Flow: reserve → charge (from reservation) → release leftover. ``available = balance − reserved``.
All mutations lock the wallet row (``SELECT … FOR UPDATE``) so concurrent sends cannot overdraw,
and every entry carries a unique ``idempotency_key`` so retries can never double-post.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import utcnow
from app.core.errors import InsufficientFunds, NotFound
from app.modules.wallet.models import LedgerEntry, PricingRule, Wallet
from app.shared.money import ZERO, money


async def get_wallet(session: AsyncSession, tenant_id: uuid.UUID, *, for_update: bool = False) -> Wallet:
    stmt = select(Wallet).where(Wallet.tenant_id == tenant_id)
    if for_update:
        stmt = stmt.with_for_update()
    wallet = await session.scalar(stmt)
    if wallet is None:
        raise NotFound("Wallet not found")
    if for_update:
        await session.refresh(wallet)
    return wallet


def available(wallet: Wallet) -> Decimal:
    return money(wallet.balance) - money(wallet.reserved)


async def _existing(session: AsyncSession, idempotency_key: str) -> LedgerEntry | None:
    return await session.scalar(select(LedgerEntry).where(LedgerEntry.idempotency_key == idempotency_key))


async def post(
    session: AsyncSession,
    wallet: Wallet,
    entry_type: str,
    *,
    amount: Decimal = ZERO,
    reserved_delta: Decimal = ZERO,
    idempotency_key: str,
    reference_type: str | None = None,
    reference_id: object = None,
    description: str | None = None,
    created_by: uuid.UUID | None = None,
) -> LedgerEntry | None:
    """Append one ledger entry and update the cached wallet values.

    ``amount`` is the signed change to ``balance``; ``reserved_delta`` the signed change to
    ``reserved``. Returns ``None`` if an entry with the same idempotency key already exists.
    The caller must hold the wallet row lock (``get_wallet(..., for_update=True)``).
    """
    if await _existing(session, idempotency_key) is not None:
        return None
    amount = money(amount)
    reserved_delta = money(reserved_delta)
    wallet.balance = money(wallet.balance) + amount
    wallet.reserved = max(ZERO, money(wallet.reserved) + reserved_delta)
    entry = LedgerEntry(
        tenant_id=wallet.tenant_id,
        wallet_id=wallet.id,
        type=entry_type,
        amount=amount,
        reserved_delta=reserved_delta,
        balance_after=wallet.balance,
        reserved_after=wallet.reserved,
        reference_type=reference_type,
        reference_id=str(reference_id) if reference_id is not None else None,
        idempotency_key=idempotency_key,
        description=description,
        created_by=created_by,
    )
    session.add(entry)
    await session.flush()
    return entry


async def reserve(
    session: AsyncSession, wallet: Wallet, amount: Decimal, *, key: str, reference_type: str, reference_id: object
) -> LedgerEntry | None:
    amount = money(amount)
    if amount <= 0:
        return None
    if available(wallet) < amount:
        raise InsufficientFunds(
            f"Insufficient balance: available {available(wallet)} {wallet.currency}, required {amount}",
            details={"available": str(available(wallet)), "required": str(amount)},
        )
    return await post(
        session, wallet, "reserve", reserved_delta=amount, idempotency_key=key,
        reference_type=reference_type, reference_id=reference_id,
    )


async def release(
    session: AsyncSession, wallet: Wallet, amount: Decimal, *, key: str, reference_type: str, reference_id: object
) -> LedgerEntry | None:
    amount = min(money(amount), money(wallet.reserved))
    if amount <= 0:
        return None
    return await post(
        session, wallet, "release", reserved_delta=-amount, idempotency_key=key,
        reference_type=reference_type, reference_id=reference_id,
    )


async def charge(
    session: AsyncSession,
    wallet: Wallet,
    amount: Decimal,
    *,
    from_reserved: Decimal,
    key: str,
    reference_type: str,
    reference_id: object,
) -> LedgerEntry | None:
    """Charge ``amount``; ``from_reserved`` of it was previously reserved, the rest must be available."""
    amount = money(amount)
    from_reserved = min(money(from_reserved), amount, money(wallet.reserved))
    extra = amount - from_reserved
    if extra > 0 and available(wallet) < extra:
        raise InsufficientFunds("Insufficient balance to cover message cost")
    return await post(
        session, wallet, "charge", amount=-amount, reserved_delta=-from_reserved, idempotency_key=key,
        reference_type=reference_type, reference_id=reference_id,
    )


async def credit(
    session: AsyncSession,
    wallet: Wallet,
    amount: Decimal,
    *,
    entry_type: str,
    key: str,
    reference_type: str | None = None,
    reference_id: object = None,
    description: str | None = None,
    created_by: uuid.UUID | None = None,
) -> LedgerEntry | None:
    assert entry_type in ("topup", "bonus", "adjustment", "refund")
    return await post(
        session, wallet, entry_type, amount=amount, idempotency_key=key, reference_type=reference_type,
        reference_id=reference_id, description=description, created_by=created_by,
    )


async def price_per_segment(session: AsyncSession, tenant_id: uuid.UUID, category: str) -> Decimal:
    """Tenant+category > tenant > global+category > global > settings default."""
    now = utcnow()
    rules = (
        await session.scalars(
            select(PricingRule)
            .where(
                or_(PricingRule.tenant_id == tenant_id, PricingRule.tenant_id.is_(None)),
                or_(PricingRule.message_category == category, PricingRule.message_category.is_(None)),
                PricingRule.effective_from <= now,
            )
            .order_by(PricingRule.effective_from.desc())
        )
    ).all()

    def rank(r: PricingRule) -> int:
        return (0 if r.tenant_id else 2) + (0 if r.message_category else 1)

    if rules:
        best = min(rules, key=lambda r: (rank(r), -r.effective_from.timestamp()))
        return money(best.price_per_segment)
    return money(settings.default_price_per_segment)


async def consume_demo_credits(session: AsyncSession, wallet: Wallet, segments: int) -> None:
    if wallet.demo_credits < segments:
        raise InsufficientFunds(
            f"Not enough demo credits: {wallet.demo_credits} left, {segments} required",
            code="insufficient_demo_credits",
        )
    wallet.demo_credits -= segments


async def reconcile(session: AsyncSession, wallet: Wallet) -> dict[str, Decimal]:
    """Compare cached values with the ledger sums."""
    row = (
        await session.execute(
            select(
                func.coalesce(func.sum(LedgerEntry.amount), 0),
                func.coalesce(func.sum(LedgerEntry.reserved_delta), 0),
            ).where(LedgerEntry.wallet_id == wallet.id)
        )
    ).one()
    ledger_balance, ledger_reserved = money(row[0]), money(row[1])
    return {
        "cached_balance": money(wallet.balance),
        "ledger_balance": ledger_balance,
        "cached_reserved": money(wallet.reserved),
        "ledger_reserved": ledger_reserved,
        "balance_diff": money(wallet.balance) - ledger_balance,
        "reserved_diff": money(wallet.reserved) - ledger_reserved,
    }


def needs_low_balance_alert(wallet: Wallet) -> bool:
    if available(wallet) >= money(wallet.low_balance_threshold):
        return False
    last = wallet.low_balance_notified_at
    return last is None or last < utcnow() - timedelta(hours=24)

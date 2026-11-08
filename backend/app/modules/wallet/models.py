from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TenantMixin, TimestampMixin, UTCDateTime, utcnow
from app.shared.money import MoneyType

LEDGER_TYPES = ("topup", "reserve", "release", "charge", "refund", "adjustment", "bonus")


class Wallet(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "wallets"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_wallets_tenant"),)

    balance: Mapped[Decimal] = mapped_column(MoneyType, default=Decimal(0))
    reserved: Mapped[Decimal] = mapped_column(MoneyType, default=Decimal(0))
    currency: Mapped[str] = mapped_column(String(3), default="LKR")
    low_balance_threshold: Mapped[Decimal] = mapped_column(MoneyType, default=Decimal(500))
    low_balance_notified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # Demo credits (segments). Separate from real money and never billed.
    demo_credits: Mapped[int] = mapped_column(Integer, default=0)


class LedgerEntry(IdMixin, TenantMixin, Base):
    """Append-only. Never UPDATE or DELETE rows of this table."""

    __tablename__ = "ledger_entries"

    wallet_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("wallets.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(16))
    # Signed effect on the field it touches: balance for topup/charge/refund/adjustment/bonus,
    # reserved for reserve/release.
    amount: Mapped[Decimal] = mapped_column(MoneyType)
    reserved_delta: Mapped[Decimal] = mapped_column(MoneyType, default=Decimal(0))
    balance_after: Mapped[Decimal] = mapped_column(MoneyType)
    reserved_after: Mapped[Decimal] = mapped_column(MoneyType)
    reference_type: Mapped[str | None] = mapped_column(String(32))
    reference_id: Mapped[str | None] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    description: Mapped[str | None] = mapped_column(String(255))
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class PricingRule(IdMixin, TimestampMixin, Base):
    __tablename__ = "pricing_rules"

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )  # NULL = global
    message_category: Mapped[str | None] = mapped_column(String(16))  # NULL = any
    price_per_segment: Mapped[Decimal] = mapped_column(MoneyType)
    effective_from: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

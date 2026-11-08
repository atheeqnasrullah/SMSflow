from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, JSONType, TenantMixin, TimestampMixin, UTCDateTime
from app.shared.money import MoneyType


class CreditPackage(IdMixin, TimestampMixin, Base):
    __tablename__ = "credit_packages"

    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(String(255))
    price_lkr: Mapped[Decimal] = mapped_column(MoneyType)
    credits: Mapped[Decimal] = mapped_column(MoneyType)  # LKR credited to wallet
    bonus_credits: Mapped[Decimal] = mapped_column(MoneyType, default=Decimal(0))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Payment(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "payments"

    package_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("credit_packages.id"))
    order_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    amount: Mapped[Decimal] = mapped_column(MoneyType)
    credits: Mapped[Decimal] = mapped_column(MoneyType)
    bonus_credits: Mapped[Decimal] = mapped_column(MoneyType, default=Decimal(0))
    currency: Mapped[str] = mapped_column(String(3), default="LKR")
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|completed|failed|cancelled|expired
    gateway: Mapped[str] = mapped_column(String(16), default="payhere")
    gateway_payment_id: Mapped[str | None] = mapped_column(String(80))
    raw_notification: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class Invoice(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "invoices"

    payment_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("payments.id"), unique=True)
    number: Mapped[str] = mapped_column(String(32), unique=True)
    sequence: Mapped[int] = mapped_column(Integer, unique=True)
    amount: Mapped[Decimal] = mapped_column(MoneyType)
    currency: Mapped[str] = mapped_column(String(3), default="LKR")
    pdf_key: Mapped[str | None] = mapped_column(String(400))
    issued_at: Mapped[datetime] = mapped_column(UTCDateTime)

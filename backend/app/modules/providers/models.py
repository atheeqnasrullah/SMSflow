from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin
from app.shared.money import MoneyType


class Provider(IdMixin, TimestampMixin, Base):
    """Platform-level SMS provider configuration (not tenant-owned)."""

    __tablename__ = "providers"

    name: Mapped[str] = mapped_column(String(80))
    type: Mapped[str] = mapped_column(String(32))  # demo | smslenz | textlk | twilio | ...
    code: Mapped[str] = mapped_column(String(32), unique=True)  # used in DLR callback URLs
    config_encrypted: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, default=100)  # lower = preferred
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    cost_per_segment: Mapped[Decimal] = mapped_column(MoneyType, default=Decimal(0))
    max_tps: Mapped[int] = mapped_column(Integer, default=20)
    categories: Mapped[str] = mapped_column(String(80), default="otp,transactional,promotional")

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, JSONType, TenantMixin, TimestampMixin, UTCDateTime
from app.shared.money import MoneyType

CAMPAIGN_STATUSES = ("draft", "scheduled", "processing", "paused", "completed", "cancelled")


class Campaign(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "campaigns"

    name: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    template_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("templates.id", ondelete="SET NULL"))
    sender: Mapped[str | None] = mapped_column(String(15))
    category: Mapped[str] = mapped_column(String(16), default="promotional")
    # {"group_ids": [...], "contact_ids": [...], "numbers": ["+9477..."]}
    audience: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    recurrence: Mapped[str | None] = mapped_column(String(255))  # iCal RRULE
    parent_campaign_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    missing_variable_policy: Mapped[str] = mapped_column(String(16), default="skip")  # skip|fallback
    missing_variable_fallback: Mapped[str] = mapped_column(String(60), default="")
    estimated_recipients: Mapped[int] = mapped_column(Integer, default=0)
    estimated_segments: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost: Mapped[Decimal] = mapped_column(MoneyType, default=Decimal(0))
    reserved_outstanding: Mapped[Decimal] = mapped_column(MoneyType, default=Decimal(0))
    expansion_done: Mapped[bool] = mapped_column(Boolean, default=False)
    skipped: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    stats: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    notes: Mapped[str | None] = mapped_column(Text)

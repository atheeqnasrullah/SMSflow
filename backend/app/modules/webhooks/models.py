from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, JSONType, TenantMixin, TimestampMixin, UTCDateTime

WEBHOOK_EVENTS = (
    "message.accepted",
    "message.delivered",
    "message.failed",
    "campaign.completed",
    "wallet.low_balance",
    "payment.completed",
)


class WebhookEndpoint(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "webhook_endpoints"

    url: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(String(200))
    secret_encrypted: Mapped[str] = mapped_column(Text)
    events: Mapped[list[str]] = mapped_column(JSONType, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    disabled_reason: Mapped[str | None] = mapped_column(String(200))


class WebhookDelivery(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "webhook_deliveries"

    endpoint_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("webhook_endpoints.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[str | None] = mapped_column(Text)
    next_retry_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|succeeded|failed
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

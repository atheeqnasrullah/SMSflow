from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, JSONType, TenantMixin, TimestampMixin, UTCDateTime, utcnow
from app.shared.money import MoneyType

TERMINAL_STATUSES = ("delivered", "undelivered", "failed", "rejected", "unknown")
IN_FLIGHT_STATUSES = ("queued", "submitting")


class Message(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_tenant_campaign_status", "tenant_id", "campaign_id", "status"),
        Index("ix_messages_provider_ref", "provider_id", "provider_message_id"),
        Index("ix_messages_tenant_created", "tenant_id", "created_at"),
        Index("ix_messages_status_updated", "status", "updated_at"),
    )

    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("campaigns.id", ondelete="SET NULL")
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    source: Mapped[str] = mapped_column(String(16))  # campaign | api | otp | dashboard
    category: Mapped[str] = mapped_column(String(16), default="transactional")
    channel: Mapped[str] = mapped_column(String(16), default="sms")  # future: whatsapp, email
    to_e164: Mapped[str] = mapped_column(String(20))
    sender: Mapped[str] = mapped_column(String(15))
    body: Mapped[str] = mapped_column(Text)
    encoding: Mapped[str] = mapped_column(String(8))
    segments: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(MoneyType, default=Decimal(0))
    cost: Mapped[Decimal] = mapped_column(MoneyType, default=Decimal(0))
    reserved_amount: Mapped[Decimal] = mapped_column(MoneyType, default=Decimal(0))
    charged: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    provider_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    provider_code: Mapped[str | None] = mapped_column(String(32))
    provider_message_id: Mapped[str | None] = mapped_column(String(128))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONType, default=dict)


class MessageEvent(IdMixin, TenantMixin, Base):
    __tablename__ = "message_events"

    message_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16))
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class IdempotencyRecord(IdMixin, TenantMixin, Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("tenant_id", "key", name="uq_idempotency_tenant_key"),)

    key: Mapped[str] = mapped_column(String(255))
    request_hash: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int] = mapped_column(Integer)
    response: Mapped[dict[str, Any]] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class OtpRequest(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "otp_requests"

    to_e164: Mapped[str] = mapped_column(String(20), index=True)
    purpose: Mapped[str] = mapped_column(String(40), default="verification")
    code_hash: Mapped[str] = mapped_column(String(64))
    message_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    note: Mapped[str | None] = mapped_column(Text)

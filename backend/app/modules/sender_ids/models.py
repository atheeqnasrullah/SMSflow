from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TenantMixin, TimestampMixin, UTCDateTime


class SenderId(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "sender_ids"
    __table_args__ = (UniqueConstraint("tenant_id", "value", name="uq_sender_ids_tenant_value"),)

    value: Mapped[str] = mapped_column(String(15))
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|approved|rejected
    purpose: Mapped[str | None] = mapped_column(Text)
    provider_ref: Mapped[str | None] = mapped_column(String(120))
    requested_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    rejection_reason: Mapped[str | None] = mapped_column(Text)

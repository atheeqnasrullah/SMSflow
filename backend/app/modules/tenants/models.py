from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TenantMixin, TimestampMixin, UTCDateTime


class Tenant(IdMixin, TimestampMixin, Base):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    business_type: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | suspended | pending
    mode: Mapped[str] = mapped_column(String(8), default="demo")  # demo | live
    country: Mapped[str] = mapped_column(String(2), default="LK")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Colombo")
    contact_email: Mapped[str | None] = mapped_column(String(320))
    contact_phone: Mapped[str | None] = mapped_column(String(20))
    address: Mapped[str | None] = mapped_column(Text)
    suspended_reason: Mapped[str | None] = mapped_column(Text)
    live_requested_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Membership(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uq_memberships_tenant_user"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | disabled


class Invitation(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "invitations"

    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(16))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    accepted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class SupportTicket(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "support_tickets"

    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | pending | closed
    priority: Mapped[str] = mapped_column(String(16), default="normal")  # low | normal | high
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    admin_notes: Mapped[str | None] = mapped_column(Text)

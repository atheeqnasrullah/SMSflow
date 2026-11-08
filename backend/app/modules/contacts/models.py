from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, JSONType, TenantMixin, TimestampMixin, UTCDateTime


class Contact(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("tenant_id", "phone_e164", name="uq_contacts_tenant_phone"),)

    phone_e164: Mapped[str] = mapped_column(String(20))
    first_name: Mapped[str | None] = mapped_column(String(120))
    last_name: Mapped[str | None] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(320))
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    language: Mapped[str] = mapped_column(String(8), default="en")
    consent_status: Mapped[str] = mapped_column(String(16), default="unknown")  # granted|revoked|unknown
    consent_source: Mapped[str | None] = mapped_column(String(120))
    consent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class ContactGroup(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "contact_groups"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_contact_groups_tenant_name"),)

    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)


class ContactGroupMember(IdMixin, TenantMixin, Base):
    __tablename__ = "contact_group_members"
    __table_args__ = (UniqueConstraint("group_id", "contact_id", name="uq_group_members_group_contact"),)

    group_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("contact_groups.id", ondelete="CASCADE"), index=True
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("contacts.id", ondelete="CASCADE"), index=True)


class Suppression(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "suppressions"
    __table_args__ = (UniqueConstraint("tenant_id", "phone_e164", name="uq_suppressions_tenant_phone"),)

    phone_e164: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(16))  # unsubscribed|complaint|invalid|manual
    note: Mapped[str | None] = mapped_column(Text)


class ImportJob(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "import_jobs"

    file_key: Mapped[str] = mapped_column(String(400))
    filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|processing|completed|failed
    group_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    consent_status: Mapped[str] = mapped_column(String(16), default="unknown")
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    imported: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, default=0)
    invalid: Mapped[int] = mapped_column(Integer, default=0)
    error_report_key: Mapped[str | None] = mapped_column(String(400))
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)

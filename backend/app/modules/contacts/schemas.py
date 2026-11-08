from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field


class ContactIn(BaseModel):
    phone: str
    first_name: str | None = Field(default=None, max_length=120)
    last_name: str | None = Field(default=None, max_length=120)
    email: EmailStr | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    language: str = Field(default="en", pattern="^(en|si|ta)$")
    consent_status: str = Field(default="unknown", pattern="^(granted|revoked|unknown)$")
    consent_source: str | None = None
    group_ids: list[uuid.UUID] = Field(default_factory=list)


class ContactUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    email: EmailStr | None = None
    attributes: dict[str, Any] | None = None
    language: str | None = Field(default=None, pattern="^(en|si|ta)$")
    consent_status: str | None = Field(default=None, pattern="^(granted|revoked|unknown)$")
    consent_source: str | None = None


class ContactOut(BaseModel):
    id: uuid.UUID
    phone_e164: str
    first_name: str | None
    last_name: str | None
    email: str | None
    attributes: dict[str, Any]
    language: str
    consent_status: str
    consent_source: str | None
    consent_at: datetime | None
    created_at: datetime
    group_ids: list[uuid.UUID] = Field(default_factory=list)
    suppressed: bool = False

    model_config = {"from_attributes": True}


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None


class GroupOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    member_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class GroupMembersIn(BaseModel):
    contact_ids: list[uuid.UUID] = Field(max_length=10000)


class SuppressionIn(BaseModel):
    phone: str
    reason: str = Field(default="manual", pattern="^(unsubscribed|complaint|invalid|manual)$")
    note: str | None = None


class SuppressionOut(BaseModel):
    id: uuid.UUID
    phone_e164: str
    reason: str
    note: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ImportJobOut(BaseModel):
    id: uuid.UUID
    filename: str
    status: str
    total_rows: int
    imported: int
    updated: int
    duplicates: int
    invalid: int
    error: str | None
    has_error_report: bool
    created_at: datetime


class BulkDeleteIn(BaseModel):
    contact_ids: list[uuid.UUID] = Field(max_length=10000)

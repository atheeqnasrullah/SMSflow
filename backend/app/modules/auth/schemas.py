from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    full_name: str = Field(min_length=2, max_length=200)
    business_name: str = Field(min_length=2, max_length=200)
    business_type: str | None = Field(default=None, max_length=80)
    phone: str | None = None
    locale: str = "en"

    @field_validator("password")
    @classmethod
    def _strength(cls, v: str) -> str:
        if v.isdigit() or v.isalpha() or v.lower() == v and not any(c.isdigit() for c in v):
            raise ValueError("Password must mix letters with digits or symbols")
        return v


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class EmailIn(BaseModel):
    email: EmailStr


class TokenIn(BaseModel):
    token: str


class ResetPasswordIn(BaseModel):
    token: str
    password: str = Field(min_length=10, max_length=128)


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=128)


class SwitchTenantIn(BaseModel):
    tenant_id: uuid.UUID


class AcceptInvitationIn(BaseModel):
    token: str
    full_name: str | None = None
    password: str | None = Field(default=None, min_length=10, max_length=128)


class WorkspaceOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    role: str
    mode: str
    status: str


class MeOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    locale: str
    email_verified: bool
    is_platform_admin: bool
    current_tenant_id: uuid.UUID | None
    role: str | None
    permissions: list[str]
    workspaces: list[WorkspaceOut]
    created_at: datetime


class UpdateProfileIn(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=200)
    locale: str | None = Field(default=None, pattern="^(en|si|ta)$")
    phone: str | None = None

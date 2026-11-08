from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, JSONType, TenantMixin, TimestampMixin


class Template(IdMixin, TimestampMixin, TenantMixin, Base):
    __tablename__ = "templates"

    name: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(Text)
    variables: Mapped[list[str]] = mapped_column(JSONType, default=list)
    category: Mapped[str] = mapped_column(String(16), default="transactional")  # otp|transactional|promotional
    language: Mapped[str] = mapped_column(String(8), default="en")

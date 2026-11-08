"""Database engine, sessions, base model and tenant (RLS) context.

Two engines:
* ``engine`` connects as the application role (no BYPASSRLS). Every tenant-scoped session sets
  ``app.tenant_id`` with ``SET LOCAL`` semantics at the start of *every* transaction, so RLS
  policies apply and the setting can never leak to another pooled connection.
* ``system_engine`` connects as the system role (BYPASSRLS) for platform-admin endpoints and
  cross-tenant background jobs (DLR lookup, due-campaign dispatch, auth lookups).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, MetaData, Uuid, event, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import NullPool
from sqlalchemy.types import TypeDecorator

from app.core.config import settings
from app.shared.ids import uuid7

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class UTCDateTime(TypeDecorator):
    """Timezone-aware datetime that is always returned in UTC (also on SQLite)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


class TenantMixin:
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )


# Tables protected by Row-Level Security (see alembic migration).
RLS_TABLES: tuple[str, ...] = (
    "contacts",
    "contact_groups",
    "contact_group_members",
    "suppressions",
    "import_jobs",
    "templates",
    "sender_ids",
    "campaigns",
    "messages",
    "message_events",
    "otp_requests",
    "wallets",
    "ledger_entries",
    "payments",
    "invoices",
    "api_keys",
    "webhook_endpoints",
    "webhook_deliveries",
    "idempotency_records",
)


def _engine_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {"echo": settings.db_echo, "future": True}
    if settings.database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"timeout": 30}
    elif settings.db_null_pool:
        kwargs["poolclass"] = NullPool
    else:
        kwargs.update(pool_pre_ping=True, pool_size=10, max_overflow=20)
    return kwargs


engine = create_async_engine(settings.database_url, **_engine_kwargs())
system_engine = (
    create_async_engine(settings.admin_database_url, **_engine_kwargs())
    if settings.admin_database_url
    else engine
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
SystemSessionLocal = async_sessionmaker(system_engine, expire_on_commit=False, autoflush=False)


if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_conn: Any, _record: Any) -> None:  # pragma: no cover - sqlite only
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()


@event.listens_for(Session, "after_begin")
def _apply_tenant_context(session: Session, _transaction: Any, connection: Any) -> None:
    """Set the RLS tenant for the transaction that just began (transaction-local)."""
    tenant_id = session.info.get("tenant_id")
    if tenant_id is not None and connection.dialect.name == "postgresql":
        connection.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)}
        )


@event.listens_for(Session, "after_commit")
def _dispatch_deferred_tasks(session: Session) -> None:
    """Enqueue background tasks only after the data they depend on is committed."""
    pending = session.info.pop("deferred_tasks", None)
    if pending:
        from app.workers.dispatch import dispatch_now

        for item in pending:
            dispatch_now(**item)


@event.listens_for(Session, "after_rollback")
def _drop_deferred_tasks(session: Session) -> None:
    session.info.pop("deferred_tasks", None)


@asynccontextmanager
async def tenant_session(tenant_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
    """Session bound to one tenant (application role, RLS enforced)."""
    async with SessionLocal() as session:
        session.info["tenant_id"] = tenant_id
        yield session


@asynccontextmanager
async def system_session() -> AsyncIterator[AsyncSession]:
    """Session for cross-tenant/system work (system role, bypasses RLS). Use sparingly."""
    async with SystemSessionLocal() as session:
        session.info["system"] = True
        yield session

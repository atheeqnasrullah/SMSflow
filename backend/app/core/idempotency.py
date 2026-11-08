"""Idempotency-Key support for send endpoints: same (tenant, key) → same response, sent once."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import utcnow
from app.core.errors import Conflict
from app.modules.messaging.models import IdempotencyRecord


def request_fingerprint(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


async def _find(session: AsyncSession, tenant_id: uuid.UUID, key: str) -> IdempotencyRecord | None:
    rec = await session.scalar(
        select(IdempotencyRecord).where(IdempotencyRecord.tenant_id == tenant_id, IdempotencyRecord.key == key)
    )
    if rec and rec.created_at < utcnow() - timedelta(hours=settings.idempotency_ttl_hours):
        await session.execute(delete(IdempotencyRecord).where(IdempotencyRecord.id == rec.id))
        await session.commit()
        return None
    return rec


async def run_idempotent(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    key: str | None,
    payload: Any,
    action: Callable[[], Awaitable[tuple[int, dict[str, Any]]]],
) -> tuple[int, dict[str, Any], bool]:
    """Execute ``action`` once per key. ``action`` must NOT commit; we commit with the record.

    Returns (status_code, response, replayed).
    """
    if not key:
        status, response = await action()
        await session.commit()
        return status, response, False
    if len(key) > 255:
        raise Conflict("Idempotency-Key too long (max 255)")
    fingerprint = request_fingerprint(payload)
    existing = await _find(session, tenant_id, key)
    if existing:
        if existing.request_hash != fingerprint:
            raise Conflict("Idempotency-Key reused with a different request body", code="idempotency_mismatch")
        return existing.status_code, existing.response, True
    status, response = await action()
    session.add(
        IdempotencyRecord(
            tenant_id=tenant_id, key=key, request_hash=fingerprint, status_code=status, response=response
        )
    )
    try:
        await session.commit()
    except IntegrityError:
        # A concurrent request with the same key won the race; everything we did is rolled back.
        await session.rollback()
        existing = await _find(session, tenant_id, key)
        if existing is None:
            raise
        return existing.status_code, existing.response, True
    return status, response, False

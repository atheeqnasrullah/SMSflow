from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog


def record(
    session: AsyncSession,
    action: str,
    *,
    tenant_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    actor_type: str = "user",
    target_type: str | None = None,
    target_id: Any = None,
    metadata: dict[str, Any] | None = None,
    ip: str | None = None,
) -> AuditLog:
    """Add an audit entry to the current transaction (committed with the action it describes)."""
    entry = AuditLog(
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        actor_type=actor_type,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        metadata_=metadata or {},
        ip=ip,
    )
    session.add(entry)
    return entry


def record_principal(
    session: AsyncSession,
    principal: Any,
    action: str,
    *,
    target_type: str | None = None,
    target_id: Any = None,
    metadata: dict[str, Any] | None = None,
    ip: str | None = None,
) -> AuditLog:
    return record(
        session,
        action,
        tenant_id=principal.tenant_id,
        actor_user_id=principal.user_id,
        actor_type=principal.kind,
        target_type=target_type,
        target_id=target_id,
        metadata={**(metadata or {}), **({"api_key_id": str(principal.api_key_id)} if principal.api_key_id else {})},
        ip=ip,
    )

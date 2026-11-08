from __future__ import annotations

import uuid

from app.modules.webhooks import service
from app.workers.registry import task


@task("webhooks.deliver", queue="webhooks")
async def deliver(delivery_id: str, tenant_id: str) -> None:
    await service.deliver(uuid.UUID(delivery_id), uuid.UUID(tenant_id))

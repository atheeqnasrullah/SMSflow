from __future__ import annotations

import uuid

from app.core.db import tenant_session
from app.modules.campaigns import service
from app.workers.registry import task


@task("campaigns.expand", queue="campaigns")
async def expand_campaign(campaign_id: str, tenant_id: str) -> None:
    await service.expand(uuid.UUID(campaign_id), uuid.UUID(tenant_id))


@task("campaigns.check_completion", queue="campaigns")
async def check_completion(campaign_id: str, tenant_id: str) -> None:
    # Debounce: large campaigns trigger this once per accepted message. Beat's dispatch_due
    # re-checks every processing campaign each minute, so a skipped final check is caught there.
    from app.core.config import settings
    from app.core.kv import get_kv

    if settings.env != "test":
        kv = get_kv()
        if await kv.get(f"cc:{campaign_id}"):
            return
        await kv.set(f"cc:{campaign_id}", "1", ex=3)
    await service.check_completion(uuid.UUID(campaign_id), uuid.UUID(tenant_id))


@task("campaigns.refresh_stats", queue="default")
async def refresh_stats(campaign_id: str, tenant_id: str) -> None:
    async with tenant_session(uuid.UUID(tenant_id)) as s:
        camp = await service.get_campaign(s, uuid.UUID(campaign_id), lock=True)
        await service.refresh_stats(s, camp)
        await s.commit()


@task("campaigns.dispatch_due", queue="campaigns")
async def dispatch_due() -> None:
    await service.dispatch_due()

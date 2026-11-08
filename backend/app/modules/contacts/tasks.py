from __future__ import annotations

import uuid

from app.modules.contacts.service import run_import
from app.workers.registry import task


@task("contacts.import", queue="default")
async def import_contacts(job_id: str, tenant_id: str) -> None:
    await run_import(uuid.UUID(job_id), uuid.UUID(tenant_id))

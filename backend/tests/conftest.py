from __future__ import annotations

import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="smsflow-test-"))
os.environ.update(
    {
        "ENV": "test",
        "DATABASE_URL": os.environ.get("TEST_DATABASE_URL", f"sqlite+aiosqlite:///{(_tmp / 'test.db').as_posix()}"),
        "TASK_MODE": "inline",
        "REDIS_URL": "memory://",
        "RATE_LIMIT_PER_SECOND": "1000",
        # pytest-asyncio gives each test its own event loop; pooled asyncpg connections would leak across loops.
        "DB_NULL_POOL": "true",
        "STORAGE_DIR": str(_tmp / "storage"),
        "QUIET_HOURS_ENABLED": "false",
        "DEMO_DLR_MIN_DELAY": "0",
        "DEMO_DLR_MAX_DELAY": "0",
        "PAYHERE_MERCHANT_ID": "1211149",
        "PAYHERE_MERCHANT_SECRET": "test-merchant-secret",
    }
)
if os.environ.get("TEST_ADMIN_DATABASE_URL"):
    os.environ["ADMIN_DATABASE_URL"] = os.environ["TEST_ADMIN_DATABASE_URL"]

import uuid  # noqa: E402
from collections.abc import AsyncIterator  # noqa: E402
from decimal import Decimal  # noqa: E402
from typing import Any  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core.db import system_engine, system_session  # noqa: E402
from app.core.kv import MemoryKV, get_kv  # noqa: E402
from app.core.security import encrypt_json, hash_password  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Base, CreditPackage, PricingRule, Provider, SenderId, Tenant, User  # noqa: E402
from app.modules.providers.router import reset_demo_provider  # noqa: E402
from app.workers.dispatch import inline_queue  # noqa: E402

PASSWORD = "Sup3r-Secret-pw"


@pytest.fixture(autouse=True)
async def _db() -> AsyncIterator[None]:
    async with system_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        if conn.dialect.name == "postgresql":
            # Mirror the migration's RLS policies so tenancy tests exercise the database layer too.
            from sqlalchemy import text

            from app.core.db import RLS_TABLES

            for table in RLS_TABLES:
                await conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
                await conn.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
                await conn.execute(text(
                    f"CREATE POLICY tenant_isolation ON {table} "
                    "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
                    "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
                ))
            await conn.execute(text(
                "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='smsflow_app') THEN "
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO smsflow_app; END IF; END $$"
            ))
    async with system_session() as s:
        s.add(Provider(name="Demo", type="demo", code="demo", config_encrypted=encrypt_json({}), priority=1000))
        s.add(PricingRule(price_per_segment=Decimal("0.85")))
        s.add(CreditPackage(name="Starter", price_lkr=Decimal("1000"), credits=Decimal("1000"), bonus_credits=Decimal("50")))
        await s.commit()
    kv = get_kv()
    if isinstance(kv, MemoryKV):
        kv.clear()
    inline_queue.clear()
    reset_demo_provider(seed=42, delivered_rate=1.0, failed_rate=0.0)
    yield
    inline_queue.clear()


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test/api/v1",
                                 headers={"X-Requested-With": "SMSFlow"}) as c:
        yield c


async def drain() -> int:
    return await inline_queue.drain(ignore_eta=True)


class Account:
    def __init__(self, client: httpx.AsyncClient, token: str, email: str) -> None:
        self.client = client
        self.token = token
        self.email = email

    @property
    def h(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    async def get(self, url: str, **kw: Any) -> httpx.Response:
        return await self.client.get(url, headers={**self.h, **kw.pop("headers", {})}, **kw)

    async def post(self, url: str, **kw: Any) -> httpx.Response:
        return await self.client.post(url, headers={**self.h, **kw.pop("headers", {})}, **kw)

    async def patch(self, url: str, **kw: Any) -> httpx.Response:
        return await self.client.patch(url, headers={**self.h, **kw.pop("headers", {})}, **kw)

    async def put(self, url: str, **kw: Any) -> httpx.Response:
        return await self.client.put(url, headers={**self.h, **kw.pop("headers", {})}, **kw)

    async def delete(self, url: str, **kw: Any) -> httpx.Response:
        return await self.client.delete(url, headers={**self.h, **kw.pop("headers", {})}, **kw)

    async def tenant_id(self) -> uuid.UUID:
        me = (await self.get("/auth/me")).json()
        return uuid.UUID(me["current_tenant_id"])


async def register(client: httpx.AsyncClient, email: str | None = None, business: str = "Acme Lanka") -> Account:
    email = email or f"user-{uuid.uuid4().hex[:8]}@example.com"
    r = await client.post("/auth/register", json={
        "email": email, "password": PASSWORD, "full_name": "Test User", "business_name": business,
    })
    assert r.status_code == 201, r.text
    return Account(client, r.json()["access_token"], email)


@pytest.fixture
async def owner(client: httpx.AsyncClient) -> Account:
    return await register(client)


@pytest.fixture
async def other_owner(client: httpx.AsyncClient) -> Account:
    return await register(client, business="Other Biz")


@pytest.fixture
async def admin(client: httpx.AsyncClient) -> Account:
    async with system_session() as s:
        s.add(User(email="root@smsflow-admin.com", password_hash=hash_password(PASSWORD), full_name="Root", is_platform_admin=True))
        await s.commit()
    r = await client.post("/auth/login", json={"email": "root@smsflow-admin.com", "password": PASSWORD})
    assert r.status_code == 200, r.text
    return Account(client, r.json()["access_token"], "root@smsflow-admin.com")


async def make_live(account: Account, *, balance: Decimal = Decimal("100"), sender: str = "ACME") -> uuid.UUID:
    """Switch a workspace to live mode with an approved sender ID and wallet credit (no admin HTTP)."""
    from app.modules.wallet import service as wallet_service

    tid = await account.tenant_id()
    async with system_session() as s:
        t = await s.get(Tenant, tid)
        assert t is not None
        t.mode = "live"
        s.add(SenderId(tenant_id=tid, value=sender, status="approved"))
        w = await wallet_service.get_wallet(s, tid, for_update=True)
        if balance:
            await wallet_service.credit(s, w, balance, entry_type="adjustment", key=f"test:{uuid.uuid4()}")
        await s.commit()
    return tid


async def add_live_provider() -> None:
    """A 'real' provider whose HTTP calls are mocked with respx in tests."""
    async with system_session() as s:
        if not await s.scalar(select(Provider.id).where(Provider.code == "mockgw")):
            s.add(Provider(name="Mock GW", type="generic", code="mockgw", priority=1, max_tps=1000,
                           config_encrypted=encrypt_json({"base_url": "https://gw.example.com", "api_token": "t",
                                                          "callback_token": "cb-secret"})))
            await s.commit()

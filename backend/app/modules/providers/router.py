"""Provider selection: demo vs real, priority, category, health (circuit breaker), and TPS throttle."""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.kv import get_kv
from app.core.security import decrypt_json
from app.modules.providers.base import SmsProvider
from app.modules.providers.demo import DemoProvider
from app.modules.providers.generic_http import GenericHttpProvider, SmslenzProvider, TextlkProvider
from app.modules.providers.models import Provider
from app.modules.providers.twilio import TwilioProvider

ADAPTERS: dict[str, type] = {
    "demo": DemoProvider,
    "twilio": TwilioProvider,
    "smslenz": SmslenzProvider,
    "textlk": TextlkProvider,
    "generic": GenericHttpProvider,
}

BREAKER_THRESHOLD = 5  # consecutive failures
BREAKER_COOLDOWN = 60  # seconds

_demo_singleton: DemoProvider | None = None


def demo_provider() -> DemoProvider:
    global _demo_singleton
    if _demo_singleton is None:
        _demo_singleton = DemoProvider()
    return _demo_singleton


def reset_demo_provider(seed: int | None = None, **config: Any) -> DemoProvider:
    global _demo_singleton
    _demo_singleton = DemoProvider(config, seed=seed)
    return _demo_singleton


def build_adapter(row: Provider) -> SmsProvider:
    if row.type == "demo":
        return demo_provider()
    cls = ADAPTERS.get(row.type)
    if cls is None:
        raise ValueError(f"Unsupported provider type {row.type}")
    return cls(decrypt_json(row.config_encrypted), provider_code=row.code)


async def is_healthy(provider_code: str) -> bool:
    open_until = await get_kv().get(f"cb:open:{provider_code}")
    return not (open_until and float(open_until) > time.time())


async def record_result(provider_code: str, ok: bool) -> None:
    kv = get_kv()
    if ok:
        await kv.delete(f"cb:fail:{provider_code}")
        return
    fails = await kv.incr(f"cb:fail:{provider_code}", ex=BREAKER_COOLDOWN * 5)
    if fails >= BREAKER_THRESHOLD:
        await kv.set(f"cb:open:{provider_code}", str(time.time() + BREAKER_COOLDOWN), ex=BREAKER_COOLDOWN)


async def acquire_tps_slot(provider_code: str, max_tps: int) -> bool:
    """Fixed one-second window token bucket. Returns False when the provider TPS is exhausted."""
    window = int(time.time())
    count = await get_kv().incr(f"tps:{provider_code}:{window}", ex=2)
    return count <= max_tps


async def select_providers(session: AsyncSession, category: str) -> list[Provider]:
    """Active real providers for a category, preferred first; unhealthy ones are moved last."""
    rows = (
        await session.scalars(
            select(Provider)
            .where(Provider.is_active.is_(True), Provider.type != "demo")
            .order_by(Provider.priority.asc())
        )
    ).all()
    eligible = [r for r in rows if category in (r.categories or "").split(",")]
    healthy = [r for r in eligible if await is_healthy(r.code)]
    unhealthy = [r for r in eligible if r not in healthy]
    return healthy + unhealthy


async def get_provider_by_code(session: AsyncSession, code: str) -> Provider | None:
    return await session.scalar(select(Provider).where(Provider.code == code))

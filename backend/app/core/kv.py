"""Tiny key-value abstraction over Redis (production) or process memory (dev/tests).

Used for rate-limit counters, API-key auth cache, circuit breakers and OTP throttles.
Redis is never the source of truth for anything that matters.
"""

from __future__ import annotations

import time
from typing import Protocol

from app.core.config import settings


class KV(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ex: int | None = None) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def incr(self, key: str, ex: int) -> int: ...


class MemoryKV:
    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float | None]] = {}

    def _alive(self, key: str) -> tuple[str, float | None] | None:
        item = self._data.get(key)
        if item and item[1] is not None and item[1] < time.monotonic():
            self._data.pop(key, None)
            return None
        return item

    async def get(self, key: str) -> str | None:
        item = self._alive(key)
        return item[0] if item else None

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._data[key] = (value, time.monotonic() + ex if ex else None)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def incr(self, key: str, ex: int) -> int:
        item = self._alive(key)
        if item is None:
            self._data[key] = ("1", time.monotonic() + ex)
            return 1
        value = int(item[0]) + 1
        self._data[key] = (str(value), item[1])
        return value

    def clear(self) -> None:
        self._data.clear()


class RedisKV:
    def __init__(self, url: str) -> None:
        import redis.asyncio as aioredis

        self._r = aioredis.from_url(url, decode_responses=True)

    async def get(self, key: str) -> str | None:
        return await self._r.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        await self._r.set(key, value, ex=ex)

    async def delete(self, key: str) -> None:
        await self._r.delete(key)

    async def incr(self, key: str, ex: int) -> int:
        async with self._r.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, ex, nx=True)
            value, _ = await pipe.execute()
        return int(value)


_kv: KV | None = None


def get_kv() -> KV:
    global _kv
    if _kv is None:
        _kv = RedisKV(settings.redis_url) if settings.redis_url.startswith("redis") else MemoryKV()
    return _kv


def reset_kv() -> None:
    """Used by Celery workers after fork and by tests."""
    global _kv
    _kv = None

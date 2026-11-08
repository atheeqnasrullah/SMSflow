"""Enqueue background work.

* :func:`defer` attaches a task to a DB session; it is dispatched **after commit** (and dropped on
  rollback) so a worker never picks up a job whose rows are not yet visible.
* :func:`enqueue` dispatches immediately (use outside a transaction).
"""

from __future__ import annotations

import asyncio
import heapq
import itertools
import time
import uuid
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

log = structlog.get_logger("smsflow.tasks")


def _jsonable(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def defer(session: AsyncSession, name: str, *, countdown: float | None = None, **kwargs: Any) -> None:
    session.info.setdefault("deferred_tasks", []).append(
        {"name": name, "kwargs": _jsonable(kwargs), "countdown": countdown}
    )


async def enqueue(name: str, *, countdown: float | None = None, **kwargs: Any) -> None:
    dispatch_now(name=name, kwargs=_jsonable(kwargs), countdown=countdown)


def dispatch_now(*, name: str, kwargs: dict[str, Any], countdown: float | None = None) -> None:
    from app.workers.registry import TASKS, load_all_tasks

    if name not in TASKS:
        load_all_tasks()
    queue = TASKS[name].queue
    if settings.task_mode == "celery":
        from app.workers.celery_app import celery_app

        celery_app.send_task(name, kwargs=kwargs, queue=queue, countdown=countdown)
    else:
        inline_queue.put(name, kwargs, countdown or 0)


class InlineQueue:
    """In-process task queue used in local dev (no Redis/Celery) and in tests."""

    def __init__(self) -> None:
        self._heap: list[tuple[float, int, str, dict[str, Any]]] = []
        self._seq = itertools.count()
        self._event: asyncio.Event | None = None

    def put(self, name: str, kwargs: dict[str, Any], countdown: float) -> None:
        heapq.heappush(self._heap, (time.monotonic() + countdown, next(self._seq), name, kwargs))
        if self._event is not None:
            self._event.set()

    def __len__(self) -> int:
        return len(self._heap)

    def clear(self) -> None:
        self._heap.clear()

    async def _run(self, name: str, kwargs: dict[str, Any]) -> None:
        from app.workers.registry import TASKS, load_all_tasks

        if name not in TASKS:
            load_all_tasks()
        try:
            await TASKS[name].fn(**kwargs)
        except Exception:  # pragma: no cover - logged, like a failed Celery task
            log.exception("inline_task_failed", task=name)
            if settings.env == "test":
                raise

    async def drain(self, *, ignore_eta: bool = True, max_tasks: int = 100_000) -> int:
        """Run queued tasks (including ones they enqueue) until the queue is empty."""
        done = 0
        while self._heap and done < max_tasks:
            eta, _, name, kwargs = self._heap[0]
            if not ignore_eta and eta > time.monotonic():
                break
            heapq.heappop(self._heap)
            await self._run(name, kwargs)
            done += 1
        return done

    async def worker_loop(self) -> None:  # pragma: no cover - dev server only
        self._event = asyncio.Event()
        while True:
            await self.drain(ignore_eta=False)
            timeout = 1.0
            if self._heap:
                timeout = max(0.05, min(1.0, self._heap[0][0] - time.monotonic()))
            self._event.clear()
            try:
                await asyncio.wait_for(self._event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                pass


inline_queue = InlineQueue()

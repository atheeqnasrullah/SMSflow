"""Registry of background tasks.

Every task is an ``async`` function with JSON-serialisable keyword arguments. The same function runs
inside a Celery worker (production) or the in-process inline queue (local dev / tests), so business
logic never depends on the execution mode.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

TaskFn = Callable[..., Awaitable[Any]]


@dataclass(frozen=True)
class TaskDef:
    name: str
    fn: TaskFn
    queue: str


TASKS: dict[str, TaskDef] = {}

QUEUES = ("campaigns", "sms.send", "sms.priority", "dlr", "webhooks", "default")


def task(name: str, queue: str = "default") -> Callable[[TaskFn], TaskFn]:
    if queue not in QUEUES:
        raise ValueError(f"unknown queue {queue}")

    def deco(fn: TaskFn) -> TaskFn:
        TASKS[name] = TaskDef(name=name, fn=fn, queue=queue)
        return fn

    return deco


def load_all_tasks() -> None:
    """Import every module that registers tasks."""
    import app.modules.auth.tasks  # noqa: F401
    import app.modules.campaigns.tasks  # noqa: F401
    import app.modules.contacts.tasks  # noqa: F401
    import app.modules.messaging.tasks  # noqa: F401
    import app.modules.payments.tasks  # noqa: F401
    import app.modules.wallet.tasks  # noqa: F401
    import app.modules.webhooks.tasks  # noqa: F401

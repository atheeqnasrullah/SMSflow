"""Celery application: queue routing, beat schedule and wrappers around registered async tasks.

Run with e.g.::

    celery -A app.workers.celery_app worker -Q sms.send,sms.priority -c 8
    celery -A app.workers.celery_app worker -Q campaigns,dlr,webhooks,default -c 4
    celery -A app.workers.celery_app beat
"""

from __future__ import annotations

import asyncio
from typing import Any

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init
from kombu import Queue

from app.core.config import settings
from app.core.logging import configure_logging, configure_sentry
from app.workers.registry import QUEUES, TASKS, load_all_tasks

celery_app = Celery("smsflow", broker=settings.broker_url)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_backend=None,
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_default_queue="default",
    task_queues=[Queue(q) for q in QUEUES],
    broker_transport_options={"visibility_timeout": 3600},
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "dispatch-due-campaigns": {
            "task": "campaigns.dispatch_due",
            "schedule": 60.0,
            "options": {"queue": "campaigns"},
        },
        "poll-pending-dlrs": {
            "task": "messaging.poll_pending_dlrs",
            "schedule": 300.0,
            "options": {"queue": "dlr"},
        },
        "sweep-stuck-messages": {
            "task": "messaging.sweep_stuck",
            "schedule": 300.0,
            "options": {"queue": "default"},
        },
        "reconcile-wallets": {
            "task": "wallet.reconcile_all",
            "schedule": crontab(hour=20, minute=30),  # 02:00 Asia/Colombo
            "options": {"queue": "default"},
        },
        "expire-pending-payments": {
            "task": "payments.expire_stale",
            "schedule": 3600.0,
            "options": {"queue": "default"},
        },
    },
)

_loop: asyncio.AbstractEventLoop | None = None


def _get_loop() -> asyncio.AbstractEventLoop:
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
    return _loop


@worker_process_init.connect
def _init_worker(**_: Any) -> None:  # pragma: no cover - runtime only
    configure_logging()
    configure_sentry("worker")
    from app.core.kv import reset_kv

    reset_kv()


def _register() -> None:
    load_all_tasks()
    for name, tdef in TASKS.items():

        def make(fn: Any) -> Any:
            def run(**kwargs: Any) -> Any:
                return _get_loop().run_until_complete(fn(**kwargs))

            return run

        celery_app.task(name=name, queue=tdef.queue, acks_late=True)(make(tdef.fn))
    celery_app.conf.task_routes = {name: {"queue": t.queue} for name, t in TASKS.items()}


_register()

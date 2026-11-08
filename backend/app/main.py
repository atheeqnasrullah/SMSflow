"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import settings
from app.core.db import engine, system_session
from app.core.errors import install_error_handlers
from app.core.kv import get_kv
from app.core.logging import configure_logging, configure_sentry

log = structlog.get_logger("smsflow.api")


async def _periodic(name: str, every: float) -> None:  # pragma: no cover - local inline mode only
    from app.workers.dispatch import enqueue

    while True:
        await asyncio.sleep(every)
        with suppress(Exception):
            await enqueue(name)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    configure_sentry("api")
    from app.workers.registry import load_all_tasks

    load_all_tasks()
    background: list[asyncio.Task] = []
    if settings.task_mode == "inline" and settings.env == "local":
        # No Redis/Celery locally: run tasks and the Beat schedule inside the API process.
        from app.workers.dispatch import inline_queue

        background.append(asyncio.create_task(inline_queue.worker_loop()))
        background.append(asyncio.create_task(_periodic("campaigns.dispatch_due", 20)))
        background.append(asyncio.create_task(_periodic("messaging.poll_pending_dlrs", 300)))
        log.info("inline_task_mode", note="tasks run in-process; use Celery in staging/production")
    yield
    for t in background:
        t.cancel()


def create_app() -> FastAPI:
    app = FastAPI(
        title="SMSFlow API",
        version="1.0.0",
        description=(
            "Bulk SMS, OTP and transactional notifications for Sri Lankan businesses.\n\n"
            "Authenticate with `Authorization: Bearer <api key>` (developers) or a dashboard JWT. "
            "`sf_test_…` keys always use the demo gateway – no real SMS is sent."
        ),
        openapi_url=f"{settings.api_prefix}/openapi.json",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        lifespan=lifespan,
    )
    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining", "Retry-After", "Idempotent-Replayed"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id, path=request.url.path)
        start = time.perf_counter()
        try:
            response: Response = await call_next(request)
        except Exception:
            log.exception("unhandled_error")
            response = JSONResponse({"error": {"code": "internal_error", "message": "Internal server error",
                                               "request_id": request_id}}, status_code=500)
        latency = int((time.perf_counter() - start) * 1000)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        principal = getattr(request.state, "principal", None)
        if principal is not None and principal.kind == "api_key":
            await _log_api_request(principal, request, response.status_code, latency, request_id)
        return response

    from app.modules.admin.router import router as admin_router
    from app.modules.api_keys.router import router as api_keys_router
    from app.modules.auth.router import router as auth_router
    from app.modules.campaigns.router import router as campaigns_router
    from app.modules.contacts.router import router as contacts_router
    from app.modules.messaging.router import balance_router
    from app.modules.messaging.router import router as sms_router
    from app.modules.otp.router import router as otp_router
    from app.modules.payments.router import callbacks as payment_callbacks
    from app.modules.payments.router import router as billing_router
    from app.modules.providers.callbacks import router as dlr_callbacks
    from app.modules.reports.router import router as reports_router
    from app.modules.sender_ids.router import router as sender_ids_router
    from app.modules.templates.router import router as templates_router
    from app.modules.tenants.router import router as workspace_router
    from app.modules.webhooks.router import router as webhooks_router

    for r in (
        auth_router, workspace_router, contacts_router, templates_router, sender_ids_router, campaigns_router,
        sms_router, balance_router, otp_router, reports_router, billing_router, api_keys_router, webhooks_router,
        admin_router, payment_callbacks, dlr_callbacks,
    ):
        app.include_router(r, prefix=settings.api_prefix)

    @app.get("/health/live", tags=["health"])
    async def live() -> dict:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    async def ready() -> JSONResponse:
        checks: dict[str, str] = {}
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as exc:  # pragma: no cover
            checks["database"] = f"error: {type(exc).__name__}"
        try:
            await get_kv().set("health", "1", ex=5)
            checks["redis"] = "ok"
        except Exception as exc:  # pragma: no cover
            checks["redis"] = f"error: {type(exc).__name__}"
        ok = all(v == "ok" for v in checks.values())
        return JSONResponse({"status": "ok" if ok else "degraded", "checks": checks}, status_code=200 if ok else 503)

    return app


async def _log_api_request(principal, request: Request, status: int, latency: int, request_id: str) -> None:  # type: ignore[no-untyped-def]
    from app.modules.api_keys.models import ApiRequestLog

    try:
        async with system_session() as s:
            s.add(ApiRequestLog(
                tenant_id=principal.tenant_id, api_key_id=principal.api_key_id, method=request.method,
                path=request.url.path[:255], status_code=status, latency_ms=latency, request_id=request_id,
            ))
            await s.commit()
    except Exception:  # pragma: no cover - logging must never break the API
        log.warning("api_request_log_failed")


app = create_app()

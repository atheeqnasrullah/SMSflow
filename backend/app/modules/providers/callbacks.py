"""Inbound delivery-report callbacks from real SMS providers."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from app.core.db import system_session
from app.core.deps import client_ip
from app.core.errors import NotFound, Unauthorized
from app.modules.providers import router as provider_router
from app.modules.providers.base import DlrRequest
from app.workers.dispatch import enqueue

router = APIRouter(prefix="/callbacks", tags=["callbacks"], include_in_schema=False)


@router.api_route("/dlr/{provider_code}", methods=["GET", "POST"])
async def dlr_callback(provider_code: str, request: Request) -> Response:
    async with system_session() as s:
        row = await provider_router.get_provider_by_code(s, provider_code)
    if row is None or row.type == "demo":
        raise NotFound("Unknown provider")
    adapter = provider_router.build_adapter(row)
    body = await request.body()
    content_type = request.headers.get("content-type", "")
    form: dict[str, str] = {}
    json_body = None
    if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        form = {k: str(v) for k, v in (await request.form()).items()}
    elif body:
        try:
            json_body = await request.json()
        except ValueError:
            json_body = None
    dlr = DlrRequest(
        headers={k.lower(): v for k, v in request.headers.items()},
        query=dict(request.query_params),
        body=body,
        form=form,
        json=json_body,
        client_ip=client_ip(request),
    )
    if not adapter.verify_callback(dlr):
        raise Unauthorized("Callback verification failed")
    for report in adapter.parse_dlr(dlr):
        await enqueue(
            "messaging.process_dlr", provider_code=provider_code, provider_message_id=report.provider_message_id,
            status=report.status, error_code=report.error_code, raw=report.raw,
        )
    return Response(status_code=200)

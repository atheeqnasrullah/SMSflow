from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.deps import Principal, RateLimit, TenantSession, require
from app.core.errors import NotFound
from app.core.permissions import P
from app.modules.templates.models import Template
from app.shared.sms_segments import analyze
from app.shared.templating import extract_variables, render

router = APIRouter(prefix="/templates", tags=["templates"], dependencies=[RateLimit])


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=1600)
    category: str = Field(default="transactional", pattern="^(otp|transactional|promotional)$")
    language: str = Field(default="en", pattern="^(en|si|ta)$")


class TemplateOut(BaseModel):
    id: uuid.UUID
    name: str
    body: str
    variables: list[str]
    category: str
    language: str
    encoding: str
    segments: int
    created_at: datetime
    updated_at: datetime


class PreviewIn(BaseModel):
    body: str = Field(max_length=1600)
    values: dict[str, Any] = Field(default_factory=dict)


class PreviewOut(BaseModel):
    rendered: str
    variables: list[str]
    missing: list[str]
    encoding: str
    length: int
    segments: int
    per_segment: int
    remaining: int
    non_gsm_chars: list[str]


def _out(t: Template) -> TemplateOut:
    info = analyze(t.body)
    return TemplateOut(
        id=t.id, name=t.name, body=t.body, variables=list(t.variables or []), category=t.category, language=t.language,
        encoding=info.encoding, segments=info.segments, created_at=t.created_at, updated_at=t.updated_at,
    )


async def _get(session: TenantSession, tenant_id: uuid.UUID | None, template_id: uuid.UUID) -> Template:
    t = await session.scalar(select(Template).where(Template.id == template_id, Template.tenant_id == tenant_id))
    if t is None:
        raise NotFound("Template not found")
    return t


@router.get("", response_model=list[TemplateOut])
async def list_templates(session: TenantSession, principal: Principal = Depends(require(P.TEMPLATES_READ)),
                         category: str | None = None) -> list[TemplateOut]:
    stmt = select(Template).where(Template.tenant_id == principal.tenant_id).order_by(Template.name)
    if category:
        stmt = stmt.where(Template.category == category)
    return [_out(t) for t in (await session.scalars(stmt)).all()]


@router.post("", response_model=TemplateOut, status_code=201)
async def create_template(data: TemplateIn, session: TenantSession, principal: Principal = Depends(require(P.TEMPLATES_WRITE))) -> TemplateOut:
    t = Template(tenant_id=principal.tenant_id, variables=extract_variables(data.body), **data.model_dump())
    session.add(t)
    await session.commit()
    return _out(t)


@router.post("/preview", response_model=PreviewOut)
async def preview(data: PreviewIn, principal: Principal = Depends(require(P.TEMPLATES_READ))) -> PreviewOut:
    variables = extract_variables(data.body)
    missing = [v for v in variables if data.values.get(v) in (None, "")]
    # Unfilled placeholders are left visible ("{{name}}") so the preview stays honest.
    values = {**data.values, **{m: "{{" + m + "}}" for m in missing}}
    rendered = render(data.body, values, fallback="")
    info = analyze(rendered)
    return PreviewOut(
        rendered=rendered, variables=variables, missing=missing, encoding=info.encoding, length=info.length,
        segments=info.segments, per_segment=info.per_segment, remaining=info.remaining, non_gsm_chars=list(info.non_gsm_chars),
    )


@router.get("/{template_id}", response_model=TemplateOut)
async def get_template(template_id: uuid.UUID, session: TenantSession, principal: Principal = Depends(require(P.TEMPLATES_READ))) -> TemplateOut:
    return _out(await _get(session, principal.tenant_id, template_id))


@router.put("/{template_id}", response_model=TemplateOut)
async def update_template(template_id: uuid.UUID, data: TemplateIn, session: TenantSession,
                          principal: Principal = Depends(require(P.TEMPLATES_WRITE))) -> TemplateOut:
    t = await _get(session, principal.tenant_id, template_id)
    for k, v in data.model_dump().items():
        setattr(t, k, v)
    t.variables = extract_variables(data.body)
    await session.commit()
    return _out(t)


@router.delete("/{template_id}", status_code=204)
async def delete_template(template_id: uuid.UUID, session: TenantSession, principal: Principal = Depends(require(P.TEMPLATES_WRITE))) -> Response:
    t = await _get(session, principal.tenant_id, template_id)
    await session.delete(t)
    await session.commit()
    return Response(status_code=204)

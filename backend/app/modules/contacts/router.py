from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, or_, select

from app.core.config import settings
from app.core.deps import Principal, RateLimit, TenantSession, require
from app.core.errors import NotFound, ValidationFailed
from app.core.permissions import P
from app.modules.contacts import service
from app.modules.contacts.models import Contact, ContactGroup, ContactGroupMember, ImportJob, Suppression
from app.modules.contacts.schemas import (
    BulkDeleteIn,
    ContactIn,
    ContactOut,
    ContactUpdate,
    GroupIn,
    GroupMembersIn,
    GroupOut,
    ImportJobOut,
    SuppressionIn,
    SuppressionOut,
)
from app.shared import storage
from app.shared.pagination import Page, PageParams, page_params, paginate
from app.workers.dispatch import defer

router = APIRouter(tags=["contacts"], dependencies=[RateLimit])


async def _contact_out(session: TenantSession, contacts: list[Contact]) -> list[ContactOut]:
    ids = [c.id for c in contacts]
    groups: dict[uuid.UUID, list[uuid.UUID]] = {}
    if ids:
        for cid, gid in await session.execute(
            select(ContactGroupMember.contact_id, ContactGroupMember.group_id).where(ContactGroupMember.contact_id.in_(ids))
        ):
            groups.setdefault(cid, []).append(gid)
    phones = [c.phone_e164 for c in contacts]
    suppressed = set()
    if phones:
        suppressed = set((await session.scalars(select(Suppression.phone_e164).where(
            Suppression.tenant_id == contacts[0].tenant_id, Suppression.phone_e164.in_(phones)))).all())
    out = []
    for c in contacts:
        item = ContactOut.model_validate(c)
        item.group_ids = groups.get(c.id, [])
        item.suppressed = c.phone_e164 in suppressed
        out.append(item)
    return out


# --- Contacts --------------------------------------------------------------------------------------
@router.get("/contacts", response_model=Page[ContactOut])
async def list_contacts(
    session: TenantSession,
    principal: Principal = Depends(require(P.CONTACTS_READ)),
    params: PageParams = Depends(page_params),
    q: str | None = None,
    group_id: uuid.UUID | None = None,
    consent_status: str | None = None,
) -> Page[ContactOut]:
    stmt = select(Contact).where(Contact.tenant_id == principal.tenant_id).order_by(Contact.created_at.desc())
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Contact.phone_e164.ilike(like), Contact.first_name.ilike(like),
                              Contact.last_name.ilike(like), Contact.email.ilike(like)))
    if group_id:
        stmt = stmt.join(ContactGroupMember, ContactGroupMember.contact_id == Contact.id).where(
            ContactGroupMember.group_id == group_id)
    if consent_status:
        stmt = stmt.where(Contact.consent_status == consent_status)
    rows, total = await paginate(session, stmt, params)
    return Page(items=await _contact_out(session, rows), total=total, page=params.page, page_size=params.page_size)


@router.post("/contacts", response_model=ContactOut, status_code=201)
async def create_contact(data: ContactIn, session: TenantSession, principal: Principal = Depends(require(P.CONTACTS_WRITE))) -> ContactOut:
    assert principal.tenant_id
    c = await service.create_contact(session, principal.tenant_id, data.model_dump())
    await session.commit()
    return (await _contact_out(session, [c]))[0]


@router.get("/contacts/export", response_class=PlainTextResponse)
async def export_contacts(
    session: TenantSession, principal: Principal = Depends(require(P.CONTACTS_READ)), group_id: uuid.UUID | None = None
) -> Response:
    assert principal.tenant_id
    body = await service.export_csv(session, principal.tenant_id, group_id)
    return Response(body, media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="contacts.csv"'})


@router.get("/contacts/{contact_id}", response_model=ContactOut)
async def get_contact(contact_id: uuid.UUID, session: TenantSession, principal: Principal = Depends(require(P.CONTACTS_READ))) -> ContactOut:
    assert principal.tenant_id
    c = await service.get_contact(session, principal.tenant_id, contact_id)
    return (await _contact_out(session, [c]))[0]


@router.patch("/contacts/{contact_id}", response_model=ContactOut)
async def update_contact(
    contact_id: uuid.UUID, data: ContactUpdate, session: TenantSession, principal: Principal = Depends(require(P.CONTACTS_WRITE))
) -> ContactOut:
    assert principal.tenant_id
    c = await service.get_contact(session, principal.tenant_id, contact_id)
    changes = data.model_dump(exclude_unset=True)
    if changes.get("consent_status") == "granted" and c.consent_status != "granted":
        from app.core.db import utcnow

        c.consent_at = utcnow()
    for k, v in changes.items():
        setattr(c, k, v)
    await session.commit()
    return (await _contact_out(session, [c]))[0]


@router.delete("/contacts/{contact_id}", status_code=204)
async def delete_contact(contact_id: uuid.UUID, session: TenantSession, principal: Principal = Depends(require(P.CONTACTS_WRITE))) -> Response:
    assert principal.tenant_id
    c = await service.get_contact(session, principal.tenant_id, contact_id)
    await session.delete(c)
    await session.commit()
    return Response(status_code=204)


@router.post("/contacts/bulk-delete")
async def bulk_delete(data: BulkDeleteIn, session: TenantSession, principal: Principal = Depends(require(P.CONTACTS_WRITE))) -> dict:
    assert principal.tenant_id
    n = await service.delete_contacts(session, principal.tenant_id, data.contact_ids)
    await session.commit()
    return {"deleted": n}


# --- Import -------------------------------------------------------------------------------------------
def _job_out(j: ImportJob) -> ImportJobOut:
    return ImportJobOut(
        id=j.id, filename=j.filename, status=j.status, total_rows=j.total_rows, imported=j.imported, updated=j.updated,
        duplicates=j.duplicates, invalid=j.invalid, error=j.error, has_error_report=bool(j.error_report_key),
        created_at=j.created_at,
    )


@router.post("/contacts/imports", response_model=ImportJobOut, status_code=202)
async def import_contacts(
    session: TenantSession,
    principal: Principal = Depends(require(P.CONTACTS_WRITE)),
    file: UploadFile = File(...),
    group_id: uuid.UUID | None = Form(None),
    consent_status: str = Form("unknown"),
) -> ImportJobOut:
    assert principal.tenant_id
    name = (file.filename or "upload.csv").lower()
    if not name.endswith((".csv", ".xlsx", ".txt")):
        raise ValidationFailed("Upload a .csv or .xlsx file")
    if consent_status not in ("granted", "unknown", "revoked"):
        raise ValidationFailed("Invalid consent_status")
    data = await file.read(settings.max_import_bytes + 1)
    if len(data) > settings.max_import_bytes:
        raise ValidationFailed(f"File too large (max {settings.max_import_bytes // 1024 // 1024} MB)")
    if group_id:
        await service.get_group(session, principal.tenant_id, group_id)
    key = storage.put_bytes(f"imports/{principal.tenant_id}", name, data)
    job = ImportJob(tenant_id=principal.tenant_id, file_key=key, filename=file.filename or name, group_id=group_id,
                    consent_status=consent_status, created_by=principal.user_id)
    session.add(job)
    await session.flush()
    defer(session, "contacts.import", job_id=job.id, tenant_id=principal.tenant_id)
    await session.commit()
    return _job_out(job)


@router.get("/contacts/imports/{job_id}", response_model=ImportJobOut)
async def get_import(job_id: uuid.UUID, session: TenantSession, principal: Principal = Depends(require(P.CONTACTS_READ))) -> ImportJobOut:
    j = await session.scalar(select(ImportJob).where(ImportJob.id == job_id, ImportJob.tenant_id == principal.tenant_id))
    if j is None:
        raise NotFound("Import not found")
    return _job_out(j)


@router.get("/contacts/imports/{job_id}/errors")
async def import_errors(job_id: uuid.UUID, session: TenantSession, principal: Principal = Depends(require(P.CONTACTS_READ))) -> Response:
    j = await session.scalar(select(ImportJob).where(ImportJob.id == job_id, ImportJob.tenant_id == principal.tenant_id))
    if j is None or not j.error_report_key:
        raise NotFound("No error report")
    return Response(storage.get_bytes(j.error_report_key), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="import-errors.csv"'})


# --- Groups ----------------------------------------------------------------------------------------------
@router.get("/groups", response_model=list[GroupOut])
async def list_groups(session: TenantSession, principal: Principal = Depends(require(P.CONTACTS_READ))) -> list[GroupOut]:
    rows = (
        await session.execute(
            select(ContactGroup, func.count(ContactGroupMember.id))
            .outerjoin(ContactGroupMember, ContactGroupMember.group_id == ContactGroup.id)
            .where(ContactGroup.tenant_id == principal.tenant_id)
            .group_by(ContactGroup.id)
            .order_by(ContactGroup.name)
        )
    ).all()
    return [GroupOut(id=g.id, name=g.name, description=g.description, member_count=n, created_at=g.created_at) for g, n in rows]


@router.post("/groups", response_model=GroupOut, status_code=201)
async def create_group(data: GroupIn, session: TenantSession, principal: Principal = Depends(require(P.CONTACTS_WRITE))) -> GroupOut:
    existing = await session.scalar(select(ContactGroup).where(ContactGroup.tenant_id == principal.tenant_id, ContactGroup.name == data.name))
    if existing:
        from app.core.errors import Conflict

        raise Conflict("A group with this name already exists")
    g = ContactGroup(tenant_id=principal.tenant_id, name=data.name, description=data.description)
    session.add(g)
    await session.commit()
    return GroupOut(id=g.id, name=g.name, description=g.description, member_count=0, created_at=g.created_at)


@router.patch("/groups/{group_id}", response_model=GroupOut)
async def update_group(group_id: uuid.UUID, data: GroupIn, session: TenantSession, principal: Principal = Depends(require(P.CONTACTS_WRITE))) -> GroupOut:
    assert principal.tenant_id
    g = await service.get_group(session, principal.tenant_id, group_id)
    g.name, g.description = data.name, data.description
    await session.commit()
    n = await session.scalar(select(func.count()).select_from(ContactGroupMember).where(ContactGroupMember.group_id == g.id))
    return GroupOut(id=g.id, name=g.name, description=g.description, member_count=int(n or 0), created_at=g.created_at)


@router.delete("/groups/{group_id}", status_code=204)
async def delete_group(group_id: uuid.UUID, session: TenantSession, principal: Principal = Depends(require(P.CONTACTS_WRITE))) -> Response:
    assert principal.tenant_id
    g = await service.get_group(session, principal.tenant_id, group_id)
    await session.delete(g)
    await session.commit()
    return Response(status_code=204)


@router.post("/groups/{group_id}/members")
async def add_members(group_id: uuid.UUID, data: GroupMembersIn, session: TenantSession, principal: Principal = Depends(require(P.CONTACTS_WRITE))) -> dict:
    assert principal.tenant_id
    n = await service.add_to_groups(session, principal.tenant_id, data.contact_ids, [group_id])
    await session.commit()
    return {"added": n}


@router.post("/groups/{group_id}/members/remove")
async def remove_members(group_id: uuid.UUID, data: GroupMembersIn, session: TenantSession, principal: Principal = Depends(require(P.CONTACTS_WRITE))) -> dict:
    assert principal.tenant_id
    from sqlalchemy import delete

    await service.get_group(session, principal.tenant_id, group_id)
    res = await session.execute(
        delete(ContactGroupMember).where(ContactGroupMember.group_id == group_id, ContactGroupMember.contact_id.in_(data.contact_ids))
    )
    await session.commit()
    return {"removed": int(res.rowcount or 0)}


# --- Suppressions ---------------------------------------------------------------------------------------
@router.get("/suppressions", response_model=Page[SuppressionOut])
async def list_suppressions(
    session: TenantSession, principal: Principal = Depends(require(P.CONTACTS_READ)),
    params: PageParams = Depends(page_params), q: str | None = Query(None),
) -> Page[SuppressionOut]:
    stmt = select(Suppression).where(Suppression.tenant_id == principal.tenant_id).order_by(Suppression.created_at.desc())
    if q:
        stmt = stmt.where(Suppression.phone_e164.ilike(f"%{q}%"))
    rows, total = await paginate(session, stmt, params)
    return Page(items=[SuppressionOut.model_validate(r) for r in rows], total=total, page=params.page, page_size=params.page_size)


@router.post("/suppressions", response_model=SuppressionOut, status_code=201)
async def add_suppression(data: SuppressionIn, session: TenantSession, principal: Principal = Depends(require(P.CONTACTS_WRITE))) -> Suppression:
    assert principal.tenant_id
    s = await service.suppress(session, principal.tenant_id, data.phone, data.reason, data.note)
    await session.commit()
    return s


@router.delete("/suppressions/{suppression_id}", status_code=204)
async def remove_suppression(suppression_id: uuid.UUID, session: TenantSession, principal: Principal = Depends(require(P.CONTACTS_WRITE))) -> Response:
    s = await session.scalar(select(Suppression).where(Suppression.id == suppression_id, Suppression.tenant_id == principal.tenant_id))
    if s is None:
        raise NotFound("Suppression not found")
    await session.delete(s)
    await session.commit()
    return Response(status_code=204)

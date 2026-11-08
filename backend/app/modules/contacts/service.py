"""Contacts, groups, suppression list, import/export."""

from __future__ import annotations

import csv
import io
import uuid
from collections.abc import Iterator
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import tenant_session, utcnow
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.modules.contacts.models import Contact, ContactGroup, ContactGroupMember, ImportJob, Suppression
from app.shared import phone as phone_util
from app.shared import storage

PHONE_HEADERS = {"phone", "mobile", "number", "phone_number", "mobile_number", "msisdn", "contact", "tel"}
HEADER_ALIASES = {
    "firstname": "first_name", "first name": "first_name", "name": "first_name", "fname": "first_name",
    "lastname": "last_name", "last name": "last_name", "surname": "last_name", "lname": "last_name",
    "e-mail": "email", "mail": "email", "lang": "language",
}
CORE_FIELDS = {"first_name", "last_name", "email", "language"}


async def get_contact(session: AsyncSession, tenant_id: uuid.UUID, contact_id: uuid.UUID) -> Contact:
    c = await session.scalar(select(Contact).where(Contact.tenant_id == tenant_id, Contact.id == contact_id))
    if c is None:
        raise NotFound("Contact not found")
    return c


async def get_group(session: AsyncSession, tenant_id: uuid.UUID, group_id: uuid.UUID) -> ContactGroup:
    g = await session.scalar(select(ContactGroup).where(ContactGroup.tenant_id == tenant_id, ContactGroup.id == group_id))
    if g is None:
        raise NotFound("Group not found")
    return g


async def add_to_groups(session: AsyncSession, tenant_id: uuid.UUID, contact_ids: list[uuid.UUID], group_ids: list[uuid.UUID]) -> int:
    added = 0
    for gid in group_ids:
        await get_group(session, tenant_id, gid)
        existing = set(
            (await session.scalars(select(ContactGroupMember.contact_id).where(ContactGroupMember.group_id == gid))).all()
        )
        valid = set(
            (await session.scalars(select(Contact.id).where(Contact.tenant_id == tenant_id, Contact.id.in_(contact_ids)))).all()
        )
        for cid in contact_ids:
            if cid in valid and cid not in existing:
                session.add(ContactGroupMember(tenant_id=tenant_id, group_id=gid, contact_id=cid))
                existing.add(cid)
                added += 1
    return added


async def create_contact(session: AsyncSession, tenant_id: uuid.UUID, data: dict[str, Any]) -> Contact:
    try:
        e164 = phone_util.normalize(data["phone"])
    except phone_util.InvalidPhoneNumber as exc:
        raise ValidationFailed(f"Invalid phone number: {data['phone']}", code="invalid_number") from exc
    if await session.scalar(select(Contact.id).where(Contact.tenant_id == tenant_id, Contact.phone_e164 == e164)):
        raise Conflict("A contact with this phone number already exists", code="duplicate_contact")
    contact = Contact(
        tenant_id=tenant_id,
        phone_e164=e164,
        first_name=data.get("first_name"),
        last_name=data.get("last_name"),
        email=data.get("email"),
        attributes=data.get("attributes") or {},
        language=data.get("language") or "en",
        consent_status=data.get("consent_status") or "unknown",
        consent_source=data.get("consent_source"),
        consent_at=utcnow() if data.get("consent_status") == "granted" else None,
    )
    session.add(contact)
    await session.flush()
    if data.get("group_ids"):
        await add_to_groups(session, tenant_id, [contact.id], data["group_ids"])
    return contact


async def suppress(session: AsyncSession, tenant_id: uuid.UUID, raw_phone: str, reason: str, note: str | None = None) -> Suppression:
    try:
        e164 = phone_util.normalize(raw_phone)
    except phone_util.InvalidPhoneNumber as exc:
        raise ValidationFailed(f"Invalid phone number: {raw_phone}") from exc
    existing = await session.scalar(select(Suppression).where(Suppression.tenant_id == tenant_id, Suppression.phone_e164 == e164))
    if existing:
        return existing
    s = Suppression(tenant_id=tenant_id, phone_e164=e164, reason=reason, note=note)
    session.add(s)
    # Unsubscribing also revokes consent on the matching contact.
    contact = await session.scalar(select(Contact).where(Contact.tenant_id == tenant_id, Contact.phone_e164 == e164))
    if contact and reason in ("unsubscribed", "complaint"):
        contact.consent_status = "revoked"
    await session.flush()
    return s


# --- Import ---------------------------------------------------------------------------------------
def _normalise_header(h: Any) -> str:
    key = str(h or "").strip().lower()
    if key in PHONE_HEADERS:
        return "phone"
    return HEADER_ALIASES.get(key, key.replace(" ", "_"))


def parse_rows(filename: str, data: bytes) -> Iterator[dict[str, Any]]:
    name = filename.lower()
    if name.endswith(".xlsx"):
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.active
        rows = ws.iter_rows(values_only=True)
        headers = [_normalise_header(h) for h in next(rows, [])]
        for values in rows:
            if values is None or all(v is None for v in values):
                continue
            yield {headers[i]: v for i, v in enumerate(values) if i < len(headers) and headers[i]}
        wb.close()
        return
    if name.endswith(".csv") or name.endswith(".txt"):
        text = data.decode("utf-8-sig", errors="replace")
        reader = csv.reader(io.StringIO(text))
        first = next(reader, None)
        if first is None:
            return
        headers = [_normalise_header(h) for h in first]
        if "phone" not in headers:
            # Header-less list of numbers
            yield {"phone": first[0]}
            for row in reader:
                if row:
                    yield {"phone": row[0]}
            return
        for row in reader:
            if not any(cell.strip() for cell in row):
                continue
            yield {headers[i]: v for i, v in enumerate(row) if i < len(headers) and headers[i]}
        return
    raise ValidationFailed("Unsupported file type; upload .csv or .xlsx")


def _phone_cell(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)  # Excel stores 771234567 as 771234567.0
    return str(value or "").strip()


async def run_import(job_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    async with tenant_session(tenant_id) as s:
        job = await s.get(ImportJob, job_id)
        if job is None or job.status not in ("pending", "processing"):
            return
        job.status = "processing"
        await s.commit()
        try:
            data = storage.get_bytes(job.file_key)
            errors: list[tuple[int, str, str]] = []
            seen: set[str] = set()
            existing = {
                c.phone_e164: c
                for c in (await s.scalars(select(Contact).where(Contact.tenant_id == tenant_id))).all()
            }
            suppressed = set((await s.scalars(select(Suppression.phone_e164).where(Suppression.tenant_id == tenant_id))).all())
            touched: list[uuid.UUID] = []
            total = imported = updated = duplicates = invalid = 0
            for idx, row in enumerate(parse_rows(job.filename, data), start=2):
                total += 1
                raw_phone = _phone_cell(row.get("phone"))
                e164 = phone_util.try_normalize(raw_phone)
                if e164 is None:
                    invalid += 1
                    errors.append((idx, raw_phone, "invalid phone number"))
                    continue
                if e164 in seen:
                    duplicates += 1
                    continue
                seen.add(e164)
                attrs = {k: (str(v) if v is not None else None) for k, v in row.items()
                         if k not in CORE_FIELDS and k != "phone" and v not in (None, "")}
                consent = job.consent_status if e164 not in suppressed else "revoked"
                contact = existing.get(e164)
                if contact is None:
                    contact = Contact(
                        tenant_id=tenant_id, phone_e164=e164,
                        first_name=(str(row.get("first_name") or "").strip() or None),
                        last_name=(str(row.get("last_name") or "").strip() or None),
                        email=(str(row.get("email") or "").strip() or None),
                        language=str(row.get("language") or "en")[:8],
                        attributes=attrs, consent_status=consent,
                        consent_source=f"import:{job.filename}" if consent == "granted" else None,
                        consent_at=utcnow() if consent == "granted" else None,
                    )
                    s.add(contact)
                    existing[e164] = contact
                    imported += 1
                else:
                    for f in ("first_name", "last_name", "email"):
                        if row.get(f):
                            setattr(contact, f, str(row[f]).strip())
                    if attrs:
                        contact.attributes = {**(contact.attributes or {}), **attrs}
                    updated += 1
                await s.flush()
                touched.append(contact.id)
            if job.group_id and touched:
                await add_to_groups(s, tenant_id, touched, [job.group_id])
            if errors:
                buf = io.StringIO()
                w = csv.writer(buf)
                w.writerow(["row", "phone", "error"])
                w.writerows(errors)
                job.error_report_key = storage.put_bytes(f"imports/{tenant_id}", "errors.csv", buf.getvalue().encode())
            job.total_rows, job.imported, job.updated, job.duplicates, job.invalid = total, imported, updated, duplicates, invalid
            job.status = "completed"
            await s.commit()
        except Exception as exc:
            await s.rollback()
            job = await s.get(ImportJob, job_id)
            if job:
                job.status = "failed"
                job.error = str(getattr(exc, "message", exc))[:1000]
                await s.commit()
            if not isinstance(exc, ValidationFailed):
                raise


# --- Export ---------------------------------------------------------------------------------------
def csv_safe(value: Any) -> str:
    """Prevent CSV/formula injection when opened in spreadsheet software."""
    text = "" if value is None else str(value)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


async def export_csv(session: AsyncSession, tenant_id: uuid.UUID, group_id: uuid.UUID | None = None) -> str:
    stmt = select(Contact).where(Contact.tenant_id == tenant_id).order_by(Contact.created_at)
    if group_id:
        stmt = stmt.join(ContactGroupMember, ContactGroupMember.contact_id == Contact.id).where(
            ContactGroupMember.group_id == group_id
        )
    contacts = (await session.scalars(stmt)).all()
    attr_keys = sorted({k for c in contacts for k in (c.attributes or {})})
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["phone", "first_name", "last_name", "email", "language", "consent_status", *attr_keys])
    for c in contacts:
        w.writerow([csv_safe(v) for v in (
            c.phone_e164, c.first_name, c.last_name, c.email, c.language, c.consent_status,
            *[(c.attributes or {}).get(k) for k in attr_keys],
        )])
    return buf.getvalue()


async def delete_contacts(session: AsyncSession, tenant_id: uuid.UUID, ids: list[uuid.UUID]) -> int:
    res = await session.execute(delete(Contact).where(Contact.tenant_id == tenant_id, Contact.id.in_(ids)))
    return int(res.rowcount or 0)

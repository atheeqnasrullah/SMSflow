"""Campaign lifecycle: draft → scheduled/processing → (paused) → completed/cancelled."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from dateutil.rrule import rrulestr
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import system_session, tenant_session, utcnow
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.modules.campaigns.models import Campaign
from app.modules.contacts.models import Contact, ContactGroupMember
from app.modules.messaging import service as msg_service
from app.modules.messaging.models import Message
from app.modules.templates.models import Template
from app.modules.tenants.models import Tenant
from app.modules.wallet import service as wallet_service
from app.shared import phone as phone_util
from app.shared.money import ZERO, money
from app.shared.sms_segments import analyze
from app.shared.templating import MissingVariable, contact_variables, extract_variables, render
from app.shared.timeutil import COLOMBO, in_quiet_hours
from app.workers.dispatch import defer


@dataclass
class Recipient:
    phone: str
    contact_id: uuid.UUID | None = None
    variables: dict[str, Any] = field(default_factory=dict)
    consent: str = "unknown"


@dataclass
class RenderedRecipient:
    recipient: Recipient
    body: str
    encoding: str
    segments: int


@dataclass
class Estimate:
    recipients: int = 0
    segments: int = 0
    unit_price: Decimal = ZERO
    cost: Decimal = ZERO
    encoding: str = "GSM7"
    skipped: dict[str, int] = field(default_factory=dict)
    rendered: list[RenderedRecipient] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        return {
            "recipients": self.recipients,
            "segments": self.segments,
            "unit_price": float(self.unit_price),
            "cost": float(self.cost),
            "currency": settings.currency,
            "encoding": self.encoding,
            "skipped": self.skipped,
        }


async def get_campaign(session: AsyncSession, campaign_id: uuid.UUID, *, lock: bool = False) -> Campaign:
    stmt = select(Campaign).where(Campaign.id == campaign_id)
    if lock:
        stmt = stmt.with_for_update()
    camp = await session.scalar(stmt)
    if camp is None:
        raise NotFound("Campaign not found")
    return camp


async def campaign_body(session: AsyncSession, camp: Campaign) -> str:
    if camp.body:
        return camp.body
    if camp.template_id:
        tpl = await session.get(Template, camp.template_id)
        if tpl:
            return tpl.body
    raise ValidationFailed("Campaign has no message body")


# --- Audience --------------------------------------------------------------------------------------
async def load_audience(
    session: AsyncSession, tenant_id: uuid.UUID, audience: dict[str, Any]
) -> tuple[list[Recipient], dict[str, int]]:
    skipped = {"invalid": 0, "duplicates": 0}
    by_phone: dict[str, Recipient] = {}

    def add(r: Recipient) -> None:
        if r.phone in by_phone:
            skipped["duplicates"] += 1
        else:
            by_phone[r.phone] = r

    cols = (
        Contact.id, Contact.phone_e164, Contact.first_name, Contact.last_name, Contact.email,
        Contact.attributes, Contact.consent_status,
    )

    def to_recipient(row: Any) -> Recipient:
        class _C:  # adapter for contact_variables
            pass

        c = _C()
        c.id, c.phone_e164, c.first_name, c.last_name, c.email, c.attributes, c.consent_status = row  # type: ignore[attr-defined]
        return Recipient(phone=row[1], contact_id=row[0], variables=contact_variables(c), consent=row[6])

    group_ids = [uuid.UUID(str(g)) for g in audience.get("group_ids") or []]
    if group_ids:
        rows = await session.execute(
            select(*cols)
            .join(ContactGroupMember, ContactGroupMember.contact_id == Contact.id)
            .where(Contact.tenant_id == tenant_id, ContactGroupMember.group_id.in_(group_ids))
            .order_by(Contact.id)
        )
        for row in rows:
            add(to_recipient(row))

    contact_ids = [uuid.UUID(str(c)) for c in audience.get("contact_ids") or []]
    for i in range(0, len(contact_ids), 1000):
        rows = await session.execute(
            select(*cols).where(Contact.tenant_id == tenant_id, Contact.id.in_(contact_ids[i : i + 1000]))
        )
        for row in rows:
            add(to_recipient(row))

    if audience.get("all_contacts"):
        rows = await session.execute(select(*cols).where(Contact.tenant_id == tenant_id).order_by(Contact.id))
        for row in rows:
            add(to_recipient(row))

    for raw in audience.get("numbers") or []:
        e164 = phone_util.try_normalize(raw)
        if e164 is None:
            skipped["invalid"] += 1
            continue
        add(Recipient(phone=e164, consent="granted"))  # uploaded lists: sender attests consent
    return list(by_phone.values()), skipped


async def build_estimate(session: AsyncSession, camp: Campaign, tenant: Tenant) -> Estimate:
    body = await campaign_body(session, camp)
    recipients, skipped = await load_audience(session, tenant.id, camp.audience or {})
    skipped.update(suppressed=0, no_consent=0, missing_variables=0)
    suppressed = await msg_service.suppressed_numbers(session, tenant.id, [r.phone for r in recipients])
    needs_vars = bool(extract_variables(body))
    est = Estimate()
    any_ucs2 = False
    for r in recipients:
        if r.phone in suppressed:
            skipped["suppressed"] += 1
            continue
        if camp.category == "promotional" and r.contact_id is not None and r.consent != "granted":
            skipped["no_consent"] += 1
            continue
        try:
            text = (
                render(
                    body, r.variables,
                    fallback=camp.missing_variable_fallback if camp.missing_variable_policy == "fallback" else None,
                )
                if needs_vars
                else body
            )
        except MissingVariable:
            skipped["missing_variables"] += 1
            continue
        info = analyze(text)
        any_ucs2 = any_ucs2 or info.encoding == "UCS2"
        est.rendered.append(RenderedRecipient(r, text, info.encoding, info.segments))
        est.segments += info.segments
    est.recipients = len(est.rendered)
    est.skipped = skipped
    est.encoding = "UCS2" if any_ucs2 else "GSM7"
    if camp.is_demo:
        est.unit_price = ZERO
        est.cost = ZERO
    else:
        est.unit_price = await wallet_service.price_per_segment(session, tenant.id, camp.category)
        est.cost = money(est.unit_price * est.segments)
    return est


# --- Lifecycle ---------------------------------------------------------------------------------------
async def launch(
    session: AsyncSession, camp: Campaign, tenant: Tenant, *, scheduled_at: datetime | None = None
) -> Estimate:
    """Reserve funds and move a draft to scheduled (future) or processing (now)."""
    if camp.status != "draft":
        raise Conflict(f"Only draft campaigns can be launched (status: {camp.status})")
    msg_service.ensure_tenant_active(tenant)
    camp.is_demo = tenant.mode == "demo"
    body = await campaign_body(session, camp)
    msg_service.check_content(body, camp.category)
    camp.sender = await msg_service.resolve_sender(session, tenant.id, camp.sender, is_demo=camp.is_demo)
    now = utcnow()
    when = max(scheduled_at or now, now)  # past schedules mean "now"
    if (
        settings.quiet_hours_enabled
        and camp.category == "promotional"
        and in_quiet_hours(when, settings.quiet_hours_start, settings.quiet_hours_end)
    ):
        raise ValidationFailed(
            f"Promotional messages cannot be sent between {settings.quiet_hours_start}:00 and "
            f"{settings.quiet_hours_end:02d}:00 (Asia/Colombo). Schedule it for later.",
            code="quiet_hours",
        )
    est = await build_estimate(session, camp, tenant)
    if est.recipients == 0:
        raise ValidationFailed("The audience has no sendable recipients", details=est.skipped)

    wallet = await wallet_service.get_wallet(session, tenant.id, for_update=True)
    if camp.is_demo:
        await wallet_service.consume_demo_credits(session, wallet, est.segments)
        camp.reserved_outstanding = ZERO
    else:
        await msg_service.check_daily_cap(session, tenant, est.recipients)
        await wallet_service.reserve(
            session, wallet, est.cost, key=f"reserve:campaign:{camp.id}:{uuid.uuid4().hex[:8]}",
            reference_type="campaign", reference_id=camp.id,
        )
        camp.reserved_outstanding = est.cost
    camp.estimated_recipients = est.recipients
    camp.estimated_segments = est.segments
    camp.estimated_cost = est.cost
    camp.skipped = est.skipped
    camp.expansion_done = False
    if scheduled_at and scheduled_at > now:
        camp.status = "scheduled"
        camp.scheduled_at = scheduled_at
    else:
        camp.status = "processing"
        camp.scheduled_at = camp.scheduled_at or now
        camp.started_at = now
        defer(session, "campaigns.expand", campaign_id=camp.id, tenant_id=tenant.id)
    return est


async def _release_outstanding(session: AsyncSession, camp: Campaign, reason: str) -> None:
    wallet = await wallet_service.get_wallet(session, camp.tenant_id, for_update=True)
    if camp.is_demo:
        used = await session.scalar(
            select(func.coalesce(func.sum(Message.segments), 0)).where(
                Message.campaign_id == camp.id,
                Message.status.in_(("accepted", "delivered", "undelivered", "unknown", "submitting")),
            )
        )
        refund = max(0, camp.estimated_segments - int(used or 0))
        wallet.demo_credits += refund
        camp.estimated_segments = int(used or 0) if reason != "unschedule" else camp.estimated_segments
        return
    if money(camp.reserved_outstanding) > 0:
        await wallet_service.release(
            session, wallet, camp.reserved_outstanding, key=f"release:campaign:{camp.id}:{reason}:{uuid.uuid4().hex[:8]}",
            reference_type="campaign", reference_id=camp.id,
        )
    camp.reserved_outstanding = ZERO


async def unschedule(session: AsyncSession, camp: Campaign) -> None:
    if camp.status != "scheduled":
        raise Conflict("Only scheduled campaigns can be unscheduled")
    await _release_outstanding(session, camp, "unschedule")
    camp.status = "draft"


async def pause(session: AsyncSession, camp: Campaign) -> None:
    if camp.status != "processing":
        raise Conflict("Only processing campaigns can be paused")
    camp.status = "paused"


async def resume(session: AsyncSession, camp: Campaign) -> None:
    if camp.status != "paused":
        raise Conflict("Only paused campaigns can be resumed")
    camp.status = "processing"
    if not camp.expansion_done:
        defer(session, "campaigns.expand", campaign_id=camp.id, tenant_id=camp.tenant_id)
    await msg_service.requeue_campaign_messages(session, camp.id, camp.tenant_id)


async def cancel(session: AsyncSession, camp: Campaign) -> None:
    if camp.status not in ("scheduled", "paused", "processing"):
        raise Conflict(f"Campaign cannot be cancelled from status {camp.status}")
    queued = (
        await session.scalars(
            select(Message).where(Message.campaign_id == camp.id, Message.status == "queued").with_for_update()
        )
    ).all()
    to_release = ZERO
    for m in queued:
        m.status = "rejected"
        m.error_code = "campaign_cancelled"
        if not m.is_demo:
            to_release += money(m.reserved_amount)
        m.reserved_amount = ZERO
    if to_release > 0:
        wallet = await wallet_service.get_wallet(session, camp.tenant_id, for_update=True)
        await wallet_service.release(
            session, wallet, to_release, key=f"release:campaign:{camp.id}:cancel-msgs",
            reference_type="campaign", reference_id=camp.id,
        )
    camp.status = "cancelled"
    camp.completed_at = utcnow()
    await session.flush()
    await _release_outstanding(session, camp, "cancel")
    await refresh_stats(session, camp)


async def duplicate(session: AsyncSession, camp: Campaign, user_id: uuid.UUID | None) -> Campaign:
    copy = Campaign(
        tenant_id=camp.tenant_id,
        name=f"{camp.name} (copy)",
        body=camp.body,
        template_id=camp.template_id,
        sender=camp.sender,
        category=camp.category,
        audience=dict(camp.audience or {}),
        missing_variable_policy=camp.missing_variable_policy,
        missing_variable_fallback=camp.missing_variable_fallback,
        recurrence=None,
        status="draft",
        created_by=user_id,
    )
    session.add(copy)
    await session.flush()
    return copy


async def refresh_stats(session: AsyncSession, camp: Campaign) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(Message.status, func.count(Message.id), func.coalesce(func.sum(Message.cost), 0))
            .where(Message.campaign_id == camp.id)
            .group_by(Message.status)
        )
    ).all()
    stats: dict[str, Any] = {s: 0 for s in ("queued", "submitting", "accepted", "delivered", "undelivered", "failed", "rejected", "unknown")}
    total = 0
    spent = ZERO
    for status, count, cost in rows:
        stats[status] = int(count)
        total += int(count)
        if status in ("accepted", "delivered", "undelivered", "unknown"):
            spent += money(cost)
    submitted = stats["accepted"] + stats["delivered"] + stats["undelivered"] + stats["unknown"]
    stats.update(
        total=total,
        submitted=submitted,
        spent=float(spent),
        delivery_rate=round(stats["delivered"] / submitted * 100, 2) if submitted else 0.0,
    )
    camp.stats = stats
    return stats


# --- Worker steps -------------------------------------------------------------------------------------
async def expand(campaign_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    """Create queued messages in batches and enqueue them. Safe to re-run (skips existing numbers)."""
    async with tenant_session(tenant_id) as s:
        camp = await get_campaign(s, campaign_id, lock=True)
        if camp.status != "processing" or camp.expansion_done:
            return
        tenant = await s.get(Tenant, tenant_id)
        assert tenant is not None
        est = await build_estimate(s, camp, tenant)
        existing = set(
            (await s.scalars(select(Message.to_e164).where(Message.campaign_id == camp.id))).all()
        )
        unit_price = est.unit_price
        todo = [r for r in est.rendered if r.recipient.phone not in existing]
        await s.commit()

    batch_size = settings.campaign_batch_size
    for i in range(0, len(todo), batch_size):
        chunk = todo[i : i + batch_size]
        async with tenant_session(tenant_id) as s:
            camp = await get_campaign(s, campaign_id, lock=True)
            if camp.status != "processing":
                return  # paused/cancelled; resume re-triggers expansion
            outstanding = money(camp.reserved_outstanding)
            for rr in chunk:
                cost = ZERO if camp.is_demo else money(unit_price * rr.segments)
                allocated = min(cost, outstanding)
                outstanding -= allocated
                m = Message(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    campaign_id=camp.id,
                    contact_id=rr.recipient.contact_id,
                    source="campaign",
                    category=camp.category,
                    to_e164=rr.recipient.phone,
                    sender=camp.sender or settings.demo_default_sender,
                    body=rr.body,
                    encoding=rr.encoding,
                    segments=rr.segments,
                    unit_price=ZERO if camp.is_demo else unit_price,
                    cost=cost,
                    reserved_amount=allocated,
                    is_demo=camp.is_demo,
                    status="queued",
                )
                s.add(m)
                defer(s, "messaging.send_message", message_id=m.id, tenant_id=tenant_id)
            camp.reserved_outstanding = outstanding
            await s.commit()

    async with tenant_session(tenant_id) as s:
        camp = await get_campaign(s, campaign_id, lock=True)
        if camp.status == "processing":
            camp.expansion_done = True
            await refresh_stats(s, camp)
            defer(s, "campaigns.check_completion", campaign_id=camp.id, tenant_id=tenant_id)
        await s.commit()


async def check_completion(campaign_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    from app.modules.webhooks.service import emit

    async with tenant_session(tenant_id) as s:
        camp = await get_campaign(s, campaign_id, lock=True)
        stats = await refresh_stats(s, camp)
        if camp.status == "processing" and camp.expansion_done and stats["queued"] == 0 and stats["submitting"] == 0:
            camp.status = "completed"
            camp.completed_at = utcnow()
            await _release_outstanding(s, camp, "final")
            await emit(s, tenant_id, "campaign.completed", {
                "campaign_id": str(camp.id), "name": camp.name, "stats": stats, "is_demo": camp.is_demo,
            })
        await s.commit()


async def check_processing_campaigns() -> None:
    """Safety net for debounced completion checks."""
    async with system_session() as s:
        rows = (
            await s.execute(
                select(Campaign.id, Campaign.tenant_id).where(
                    Campaign.status == "processing", Campaign.expansion_done.is_(True)
                )
            )
        ).all()
    for cid, tid in rows:
        await check_completion(cid, tid)


async def dispatch_due() -> int:
    """Called every minute by Beat. SKIP LOCKED makes concurrent beats safe."""
    await check_processing_campaigns()
    now = utcnow()
    async with system_session() as s:
        due = (
            await s.execute(
                select(Campaign.id, Campaign.tenant_id)
                .where(Campaign.status == "scheduled", Campaign.scheduled_at <= now)
                .with_for_update(skip_locked=True)
                .limit(200)
            )
        ).all()
        if not due:
            return 0
        ids = [d[0] for d in due]
        await s.execute(
            update(Campaign).where(Campaign.id.in_(ids)).values(status="processing", started_at=now)
        )
        for cid, tid in due:
            defer(s, "campaigns.expand", campaign_id=cid, tenant_id=tid)
        await s.commit()
    for cid, tid in due:
        await schedule_next_occurrence(cid, tid)
    return len(due)


async def schedule_next_occurrence(campaign_id: uuid.UUID, tenant_id: uuid.UUID) -> Campaign | None:
    """For recurring campaigns, materialise the next run as a new scheduled child campaign."""
    async with tenant_session(tenant_id) as s:
        camp = await get_campaign(s, campaign_id)
        if not camp.recurrence or not camp.scheduled_at:
            return None
        start_local = camp.scheduled_at.astimezone(COLOMBO)
        rule = rrulestr(camp.recurrence, dtstart=start_local)
        nxt = rule.after(start_local)
        if nxt is None:
            return None
        child = Campaign(
            tenant_id=tenant_id,
            name=camp.name,
            body=camp.body,
            template_id=camp.template_id,
            sender=camp.sender,
            category=camp.category,
            audience=dict(camp.audience or {}),
            recurrence=camp.recurrence,
            parent_campaign_id=camp.parent_campaign_id or camp.id,
            missing_variable_policy=camp.missing_variable_policy,
            missing_variable_fallback=camp.missing_variable_fallback,
            status="draft",
            created_by=camp.created_by,
        )
        s.add(child)
        await s.flush()
        tenant = await s.get(Tenant, tenant_id)
        assert tenant is not None
        try:
            await launch(s, child, tenant, scheduled_at=nxt.astimezone(camp.scheduled_at.tzinfo))
        except Exception as exc:  # insufficient funds etc. → keep as draft with a note
            child.status = "draft"
            child.notes = f"Automatic scheduling failed: {getattr(exc, 'message', str(exc))}"
        await s.commit()
        return child

"""Delivery analytics. Accepted ≠ delivered: delivery rate = delivered / submitted × 100."""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import case, func, select

from app.core.db import utcnow
from app.core.deps import Principal, RateLimit, TenantSession, require
from app.core.permissions import P
from app.modules.campaigns.models import Campaign
from app.modules.contacts.models import Contact
from app.modules.contacts.service import csv_safe
from app.modules.messaging.models import Message

router = APIRouter(prefix="/reports", tags=["reports"], dependencies=[RateLimit])

SUBMITTED = ("accepted", "delivered", "undelivered", "unknown")


def _range(days: int, date_from: datetime | None, date_to: datetime | None) -> tuple[datetime, datetime]:
    end = date_to or utcnow()
    start = date_from or end - timedelta(days=days)
    return start, end


@router.get("/overview")
async def overview(
    session: TenantSession,
    principal: Principal = Depends(require(P.REPORTS_READ)),
    days: int = Query(30, ge=1, le=366),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    include_demo: bool = True,
) -> dict[str, Any]:
    start, end = _range(days, date_from, date_to)
    base = [Message.tenant_id == principal.tenant_id, Message.created_at >= start, Message.created_at <= end]
    if not include_demo:
        base.append(Message.is_demo.is_(False))

    by_status = dict((await session.execute(
        select(Message.status, func.count(Message.id)).where(*base).group_by(Message.status)
    )).all())
    totals = (await session.execute(
        select(
            func.count(Message.id),
            func.coalesce(func.sum(Message.segments), 0),
            func.coalesce(func.sum(case((Message.charged.is_(True), Message.cost), else_=0)), 0),
        ).where(*base)
    )).one()
    day = func.date(Message.created_at)
    daily_rows = (await session.execute(
        select(
            day.label("day"),
            func.count(Message.id),
            func.sum(case((Message.status == "delivered", 1), else_=0)),
            func.sum(case((Message.status.in_(("failed", "undelivered", "rejected")), 1), else_=0)),
        ).where(*base).group_by(day).order_by(day)
    )).all()
    by_source = dict((await session.execute(
        select(Message.source, func.count(Message.id)).where(*base).group_by(Message.source)
    )).all())

    submitted = sum(int(by_status.get(s, 0)) for s in SUBMITTED)
    delivered = int(by_status.get("delivered", 0))
    contacts = await session.scalar(select(func.count(Contact.id)).where(Contact.tenant_id == principal.tenant_id))
    active_campaigns = await session.scalar(select(func.count(Campaign.id)).where(
        Campaign.tenant_id == principal.tenant_id, Campaign.status.in_(("scheduled", "processing", "paused"))))
    return {
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "total_messages": int(totals[0]),
        "total_segments": int(totals[1]),
        "spend": float(totals[2]),
        "submitted": submitted,
        "delivered": delivered,
        "delivery_rate": round(delivered / submitted * 100, 2) if submitted else 0.0,
        "by_status": {k: int(v) for k, v in by_status.items()},
        "by_source": {k: int(v) for k, v in by_source.items()},
        "daily": [
            {"date": str(d), "total": int(t), "delivered": int(dl or 0), "failed": int(f or 0)}
            for d, t, dl, f in daily_rows
        ],
        "contacts": int(contacts or 0),
        "active_campaigns": int(active_campaigns or 0),
    }


@router.get("/campaigns")
async def campaign_comparison(
    session: TenantSession, principal: Principal = Depends(require(P.REPORTS_READ)), limit: int = Query(20, le=100)
) -> list[dict[str, Any]]:
    rows = (await session.scalars(
        select(Campaign).where(Campaign.tenant_id == principal.tenant_id, Campaign.status.in_(("processing", "completed", "cancelled", "paused")))
        .order_by(Campaign.started_at.desc().nulls_last()).limit(limit)
    )).all()
    return [
        {
            "id": str(c.id), "name": c.name, "status": c.status, "is_demo": c.is_demo,
            "started_at": c.started_at.isoformat() if c.started_at else None,
            "recipients": (c.stats or {}).get("total", c.estimated_recipients),
            "delivered": (c.stats or {}).get("delivered", 0),
            "failed": (c.stats or {}).get("failed", 0) + (c.stats or {}).get("undelivered", 0),
            "delivery_rate": (c.stats or {}).get("delivery_rate", 0.0),
            "spent": (c.stats or {}).get("spent", 0.0),
        }
        for c in rows
    ]


@router.get("/messages/export")
async def export_messages(
    session: TenantSession,
    principal: Principal = Depends(require(P.REPORTS_READ)),
    days: int = Query(30, ge=1, le=366),
    status: str | None = None,
    campaign_id: str | None = None,
) -> Response:
    start, end = _range(days, None, None)
    stmt = select(Message).where(Message.tenant_id == principal.tenant_id, Message.created_at >= start,
                                 Message.created_at <= end).order_by(Message.created_at).limit(200_000)
    if status:
        stmt = stmt.where(Message.status == status)
    if campaign_id:
        stmt = stmt.where(Message.campaign_id == campaign_id)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["message_id", "created_at", "to", "sender", "source", "status", "segments", "encoding", "cost",
                "is_demo", "error_code", "delivered_at", "body"])
    for m in (await session.scalars(stmt)).all():
        w.writerow([csv_safe(v) for v in (
            m.id, m.created_at.isoformat(), m.to_e164, m.sender, m.source, m.status, m.segments, m.encoding, m.cost,
            m.is_demo, m.error_code, m.delivered_at.isoformat() if m.delivered_at else "", m.body,
        )])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="messages.csv"'})

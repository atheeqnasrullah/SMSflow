from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

COLOMBO = ZoneInfo("Asia/Colombo")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def in_quiet_hours(at: datetime, start_hour: int, end_hour: int, tz: ZoneInfo = COLOMBO) -> bool:
    local = at.astimezone(tz)
    h = local.hour
    if start_hour > end_hour:  # crosses midnight, e.g. 21 -> 8
        return h >= start_hour or h < end_hour
    return start_hour <= h < end_hour

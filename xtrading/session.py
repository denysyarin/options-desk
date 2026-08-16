"""America/New_York session gate for scheduled desk jobs."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
JobName = Literal["overnight", "premarket", "rth", "skip"]


def _as_et(now: datetime) -> datetime:
    if now.tzinfo is None:
        now = now.replace(tzinfo=ET)
    return now.astimezone(ET)


def et_date(now: datetime) -> date:
    return _as_et(now).date()


def job_for(now: datetime) -> JobName:
    local = _as_et(now)
    if local.weekday() >= 5:
        return "skip"
    hm = local.hour * 60 + local.minute
    if 9 * 60 <= hm < 9 * 60 + 30:
        return "premarket"
    if 9 * 60 + 30 <= hm < 10 * 60:
        return "rth"
    if 16 * 60 + 30 <= hm < 17 * 60:
        return "overnight"
    return "skip"

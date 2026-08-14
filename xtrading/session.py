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
    if local.hour == 9 and local.minute == 15:
        return "premarket"
    if local.hour == 9 and local.minute == 30:
        return "rth"
    if local.hour == 16 and local.minute == 30:
        return "overnight"
    return "skip"

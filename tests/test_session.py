"""America/New_York job gate for overnight vs premarket vs RTH."""
from datetime import datetime
from zoneinfo import ZoneInfo

from xtrading.session import et_date, job_for

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def test_weekday_0915_et_is_premarket():
    assert job_for(datetime(2026, 8, 14, 9, 15, tzinfo=ET)) == "premarket"


def test_weekday_1630_et_is_overnight():
    assert job_for(datetime(2026, 8, 14, 16, 30, tzinfo=ET)) == "overnight"


def test_weekday_0930_et_is_rth():
    assert job_for(datetime(2026, 8, 14, 9, 30, tzinfo=ET)) == "rth"


def test_0916_and_weekend_are_skip():
    assert job_for(datetime(2026, 8, 14, 9, 16, tzinfo=ET)) == "skip"
    assert job_for(datetime(2026, 8, 14, 9, 31, tzinfo=ET)) == "skip"
    assert job_for(datetime(2026, 8, 15, 9, 15, tzinfo=ET)) == "skip"  # Saturday
    assert job_for(datetime(2026, 8, 16, 16, 30, tzinfo=ET)) == "skip"  # Sunday


def test_utc_that_is_not_0915_et_is_skip():
    # 09:15 UTC in August is 05:15 ET
    assert job_for(datetime(2026, 8, 14, 9, 15, tzinfo=UTC)) == "skip"


def test_dst_winter_0915_et_still_premarket():
    # EST: 09:15 ET = 14:15 UTC
    assert job_for(datetime(2026, 1, 15, 9, 15, tzinfo=ET)) == "premarket"
    assert job_for(datetime(2026, 1, 15, 14, 15, tzinfo=UTC)) == "premarket"


def test_dst_winter_0930_et_still_rth():
    assert job_for(datetime(2026, 1, 15, 9, 30, tzinfo=ET)) == "rth"
    assert job_for(datetime(2026, 1, 15, 14, 30, tzinfo=UTC)) == "rth"


def test_et_date_uses_new_york_calendar():
    late_utc = datetime(2026, 8, 15, 3, 0, tzinfo=UTC)  # still Aug 14 in ET
    assert et_date(late_utc).isoformat() == "2026-08-14"

"""America/New_York job gate for overnight vs premarket vs RTH."""
from datetime import datetime
from zoneinfo import ZoneInfo

from xtrading.session import et_date, job_for

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def test_weekday_0900_to_0929_et_is_premarket():
    assert job_for(datetime(2026, 8, 14, 9, 0, tzinfo=ET)) == "premarket"
    assert job_for(datetime(2026, 8, 14, 9, 14, tzinfo=ET)) == "premarket"
    assert job_for(datetime(2026, 8, 14, 9, 15, tzinfo=ET)) == "premarket"
    assert job_for(datetime(2026, 8, 14, 9, 29, tzinfo=ET)) == "premarket"


def test_weekday_0930_to_0959_et_is_rth():
    assert job_for(datetime(2026, 8, 14, 9, 30, tzinfo=ET)) == "rth"
    assert job_for(datetime(2026, 8, 14, 9, 31, tzinfo=ET)) == "rth"
    assert job_for(datetime(2026, 8, 14, 9, 59, tzinfo=ET)) == "rth"


def test_weekday_1630_to_1659_et_is_overnight():
    assert job_for(datetime(2026, 8, 14, 16, 30, tzinfo=ET)) == "overnight"
    assert job_for(datetime(2026, 8, 14, 16, 59, tzinfo=ET)) == "overnight"


def test_edges_outside_windows_are_skip():
    assert job_for(datetime(2026, 8, 14, 8, 59, tzinfo=ET)) == "skip"
    assert job_for(datetime(2026, 8, 14, 10, 0, tzinfo=ET)) == "skip"
    assert job_for(datetime(2026, 8, 14, 16, 29, tzinfo=ET)) == "skip"
    assert job_for(datetime(2026, 8, 14, 17, 0, tzinfo=ET)) == "skip"
    assert job_for(datetime(2026, 8, 15, 9, 0, tzinfo=ET)) == "skip"  # Saturday
    assert job_for(datetime(2026, 8, 16, 16, 30, tzinfo=ET)) == "skip"  # Sunday


def test_utc_that_is_not_in_et_window_is_skip():
    # 09:15 UTC in August is 05:15 ET
    assert job_for(datetime(2026, 8, 14, 9, 15, tzinfo=UTC)) == "skip"


def test_dst_winter_0900_et_still_premarket():
    assert job_for(datetime(2026, 1, 15, 9, 0, tzinfo=ET)) == "premarket"
    assert job_for(datetime(2026, 1, 15, 14, 0, tzinfo=UTC)) == "premarket"


def test_dst_winter_0930_et_still_rth():
    assert job_for(datetime(2026, 1, 15, 9, 30, tzinfo=ET)) == "rth"
    assert job_for(datetime(2026, 1, 15, 14, 30, tzinfo=UTC)) == "rth"


def test_et_date_uses_new_york_calendar():
    late_utc = datetime(2026, 8, 15, 3, 0, tzinfo=UTC)  # still Aug 14 in ET
    assert et_date(late_utc).isoformat() == "2026-08-14"

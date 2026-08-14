"""Dated snapshot dirs for overnight RV and premarket briefs."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from xtrading.screener.snapshots import SnapshotStore, is_today_et
from xtrading.session import ET

NOW = datetime(2026, 8, 14, 9, 15, tzinfo=ET)


def test_overnight_round_trip(tmp_path):
    store = SnapshotStore(tmp_path)
    uni = pd.DataFrame({"Ticker": ["MSFT"], "Price": [500.0]})
    rv = {"MSFT": 0.21}
    meta = {"fetched_at": NOW.isoformat(), "job": "overnight", "tickers": ["MSFT"]}
    store.write_overnight(date(2026, 8, 13), universe=uni, rv=rv, meta=meta)
    loaded_date, loaded_rv = store.load_latest_rv(before=date(2026, 8, 14))
    assert loaded_date == date(2026, 8, 13)
    assert loaded_rv["MSFT"] == pytest.approx(0.21)
    assert (tmp_path / "2026-08-13" / "overnight" / "universe.csv").exists()
    assert not list(tmp_path.rglob("history"))


def test_load_latest_rv_walks_back_weekend(tmp_path):
    store = SnapshotStore(tmp_path)
    store.write_overnight(
        date(2026, 8, 14),
        universe=pd.DataFrame({"Ticker": ["A"]}),
        rv={"A": 0.3},
        meta={"fetched_at": NOW.isoformat(), "job": "overnight"},
    )
    d, rv = store.load_latest_rv(before=date(2026, 8, 17))
    assert d == date(2026, 8, 14)
    assert rv["A"] == pytest.approx(0.3)
    d2, rv2 = store.load_latest_rv(before=date(2026, 8, 14))
    assert d2 is None and rv2 == {}


def test_premarket_round_trip_and_freshness(tmp_path):
    store = SnapshotStore(tmp_path)
    snap = pd.DataFrame({"Ticker": ["BBB"], "Gap": ["2.10%"]})
    meta = {"fetched_at": NOW.isoformat(), "job": "premarket"}
    store.write_premarket(
        date(2026, 8, 14),
        snapshot=snap,
        meta=meta,
    )
    day = tmp_path / "2026-08-14" / "premarket"
    assert not (day / "brief.md").exists()
    assert not (day / "ranked.csv").exists()
    loaded_snap = store.load_premarket_snapshot(date(2026, 8, 14))
    assert list(loaded_snap["Ticker"]) == ["BBB"]
    loaded = store.read_meta(date(2026, 8, 14), "premarket")
    assert is_today_et(loaded, NOW) is True
    yesterday = {"fetched_at": datetime(2026, 8, 13, 9, 15, tzinfo=ET).isoformat()}
    assert is_today_et(yesterday, NOW) is False


def test_rth_round_trip(tmp_path):
    store = SnapshotStore(tmp_path)
    ranked = pd.DataFrame({"ticker": ["BBB"], "vrp": [0.1]})
    folder = store.write_rth(
        date(2026, 8, 14),
        ranked=ranked,
        brief="live open",
        meta={"fetched_at": NOW.isoformat(), "job": "rth"},
    )
    assert (folder / "brief.md").read_text() == "live open"
    assert (folder / "ranked.csv").exists()
    assert store.load_premarket_snapshot(date(2026, 8, 14)) is None
    assert folder.name == "rth"


def test_rth_full_job_folder(tmp_path):
    store = SnapshotStore(tmp_path)
    folder = store.write_rth(
        date(2026, 8, 14),
        ranked=pd.DataFrame({"ticker": ["AAA"], "vrp": [0.2]}),
        brief="full dump",
        meta={"chain_mode": "all_watchlist"},
        job="rth-full",
    )
    assert folder.name == "rth-full"
    assert (tmp_path / "2026-08-14" / "rth-full" / "brief.md").read_text() == "full dump"
    assert not (tmp_path / "2026-08-14" / "rth").exists()

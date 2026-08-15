from datetime import date

import pandas as pd

from xtrading.screener.lock_widget import (
    TAPE_URL,
    build_lock_widget,
    earnings_from_universe,
    lock_tape_markdown,
    month_vol_from_universe,
)
from xtrading.screener.snapshots import SnapshotStore


def test_lock_widget_ranks_six_and_tones():
    rv = {
        "SPY": 0.133,
        "MCD": 0.176,
        "AMZN": 0.616,
        "DELL": 0.860,
        "ONTO": 1.089,
        "SPCX": 1.040,
        "IREN": 1.490,
        "NBIS": 1.882,
    }
    payload = build_lock_widget(
        rv,
        as_of=date(2026, 8, 14),
        month_vol={"NBIS": 1.894, "IREN": 1.554, "ONTO": 1.135},
    )
    assert payload["label"] == "RV"
    tickers = [row["ticker"] for row in payload["hot"]]
    assert tickers == ["NBIS", "IREN", "ONTO", "SPCX", "DELL", "AMZN"]
    tones = {row["ticker"]: row["tone"] for row in payload["hot"]}
    assert tones["NBIS"] == "hot"
    assert tones["IREN"] == "hot"
    assert tones["ONTO"] == "mid"
    assert tones["SPCX"] == "mid"
    assert tones["DELL"] == "mid"
    assert tones["AMZN"] == "cold"
    by_vol = {row["ticker"]: row.get("month_vol") for row in payload["hot"]}
    assert by_vol["NBIS"] == 1.894
    assert by_vol["SPCX"] is None
    click = payload["click_url"]
    assert click == TAPE_URL
    assert "claude.ai" not in click
    assert "auth=" not in click
    tape = lock_tape_markdown(payload)
    assert "# RV tape" in tape
    assert "NBIS" in tape
    assert "Toward 09:30" in tape
    assert "IREN" in tape


def test_lock_widget_marks_earnings_inside_two_weeks_only():
    rv = {"NVDA": 0.4, "AAPL": 0.3, "MSFT": 0.2, "GLD": 0.1}
    payload = build_lock_widget(
        rv,
        as_of=date(2026, 8, 15),
        earnings={"NVDA": date(2026, 8, 26), "AAPL": date(2026, 7, 30)},
    )
    by = {row["ticker"]: row["earn"] for row in payload["hot"]}
    assert by["NVDA"] is True
    assert by["AAPL"] is False
    tape = lock_tape_markdown(payload)
    assert "soon" in tape
    assert "NVDA" in tape


def test_write_overnight_also_writes_stable_lock_widget(tmp_path):
    store = SnapshotStore(tmp_path)
    uni = pd.DataFrame({
        "Ticker": ["NBIS", "SPY"],
        "earnings_date": [date(2026, 8, 26), None],
        "range_vol_ann": [1.89, 0.15],
    })
    folder = store.write_overnight(
        date(2026, 8, 14),
        universe=uni,
        rv={"NBIS": 1.8, "SPY": 0.13},
        meta={"fetched_at": "2026-08-14T16:30:00-04:00", "job": "overnight"},
    )
    lock = tmp_path / "lock-widget.json"
    tape = tmp_path / "lock-tape.md"
    assert lock.exists()
    assert tape.exists()
    assert (folder / "rv.json").exists()
    text = lock.read_text()
    assert "NBIS" in text
    assert "month_vol" in text
    assert "auth=" not in text
    assert TAPE_URL in text
    assert "claude.ai" not in text
    assert "NBIS" in tape.read_text()


def test_earnings_from_universe_maps_ticker():
    uni = pd.DataFrame({"Ticker": ["dell"], "earnings_date": [date(2026, 9, 3)]})
    assert earnings_from_universe(uni)["DELL"] == date(2026, 9, 3)


def test_month_vol_from_universe_maps_ticker():
    uni = pd.DataFrame({"Ticker": ["nbis"], "range_vol_ann": [1.894]})
    assert month_vol_from_universe(uni)["NBIS"] == 1.894

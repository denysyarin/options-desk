"""Deterministic premarket brief from ranked puts + gap snapshot."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from xtrading.screener.brief import format_brief

ET = ZoneInfo("America/New_York")
NOW = datetime(2026, 8, 14, 9, 15, tzinfo=ET)


def test_brief_includes_vrp_gap_source_and_flags_not_token():
    ranked = pd.DataFrame([{
        "ticker": "BBB", "strike": 96.0, "dte": 7, "bid": 1.4, "ask": 1.5,
        "mid": 1.45, "delta": -0.18, "iv": 0.45, "rv_20d": 0.25, "vrp": 0.20,
        "annualized_roc": 0.8, "spread_pct": 0.069, "iv_unreliable": True,
    }])
    snapshot = pd.DataFrame([{
        "Ticker": "BBB", "Gap": "3.10%", "Price": 100.0, "Relative Volume": 2.1,
    }])
    text = format_brief(
        ranked,
        snapshot,
        meta={
            "fetched_at": NOW.isoformat(),
            "job": "rth",
            "rv_source": "quote_20d",
            "empty_universe": False,
        },
    )
    assert "BBB" in text
    assert "VRP" in text or "vrp" in text.lower()
    assert "3.10%" in text or "3.1" in text
    assert "quote_20d" in text
    assert "FLAG" in text or "unreliable" in text.lower()
    assert "not advice" in text.lower() or "not financial advice" in text.lower()
    assert "cash is open" in text.lower()
    assert "auth=" not in text


def test_empty_universe_brief():
    text = format_brief(
        pd.DataFrame(),
        pd.DataFrame(),
        meta={"fetched_at": NOW.isoformat(), "empty_universe": True, "rv_source": "none"},
    )
    assert "empty" in text.lower() or "no liquid" in text.lower()

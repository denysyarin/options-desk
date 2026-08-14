"""Overnight RV cache and 9:15 premarket desk jobs."""
from datetime import datetime

import pandas as pd
import pytest

from tests.test_put_premium import FakeProvider
from xtrading.screener.jobs import SessionSkip, run_overnight, run_premarket
from xtrading.session import ET

PREMARKET_NOW = datetime(2026, 8, 14, 9, 15, tzinfo=ET)
OVERNIGHT_NOW = datetime(2026, 8, 13, 16, 30, tzinfo=ET)


class DeskProvider(FakeProvider):
    def fetch_screener(self, filters: str, **kwargs):
        df = super().fetch_screener(filters, **kwargs)
        df["Gap"] = ["0.1%", "3.10%", "1.00%", "-0.50%", "0.00%"]
        df["Previous Close"] = df["Price"]
        return df


def test_overnight_wrong_window_skips():
    with pytest.raises(SessionSkip):
        run_overnight(
            DeskProvider(),
            filters="x",
            snapshot_root="unused",
            now=lambda: PREMARKET_NOW,  # 09:15
            top_n=3,
            force=False,
        )


def test_overnight_pulls_history_for_top_20_not_options(tmp_path):
    p = DeskProvider()
    folder = run_overnight(
        p,
        filters="sh_opt_option",
        snapshot_root=tmp_path,
        now=lambda: OVERNIGHT_NOW,
        top_n=3,
        force=False,
    )
    hist = [c for c in p.calls if c.startswith("history:")]
    assert hist == ["history:BBB", "history:CCC", "history:DDD"]
    assert not any(c.startswith("chain:") for c in p.calls)
    assert (folder / "rv.json").exists()
    assert (folder / "universe.csv").exists()
    rv = pd.read_json(folder / "rv.json", typ="series")
    assert "BBB" in set(rv.index.astype(str)) or "BBB" in rv.to_dict()


def test_premarket_uses_overnight_rv_and_skips_quote_export(tmp_path, capsys):
    p = DeskProvider()
    run_overnight(
        p, filters="f", snapshot_root=tmp_path, now=lambda: OVERNIGHT_NOW, top_n=3,
    )
    p.calls.clear()
    folder = run_premarket(
        p,
        filters="f",
        snapshot_root=tmp_path,
        now=lambda: PREMARKET_NOW,
        top_n=3,
    )
    assert not any(c.startswith("history:") for c in p.calls)
    assert any(c.startswith("screener:") for c in p.calls)
    assert any(c.startswith("chain:") for c in p.calls)
    brief = (folder / "brief.md").read_text()
    assert "quote_20d" in brief
    assert "BBB" in brief or "no surviving" in brief.lower()
    meta = (folder / "meta.json").read_text()
    assert "test-token" not in meta
    assert "auth=" not in meta


def test_premarket_without_overnight_falls_back_to_month_vol(tmp_path):
    p = DeskProvider()
    folder = run_premarket(
        p, filters="f", snapshot_root=tmp_path, now=lambda: PREMARKET_NOW, top_n=3, force=True,
    )
    brief = (folder / "brief.md").read_text()
    assert "screener_month_vol" in brief

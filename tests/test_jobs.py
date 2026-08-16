"""Overnight RV cache, 9:00 prelayer, and 9:30 RTH desk jobs."""
import json
from datetime import datetime

import pandas as pd
import pytest

from tests.test_put_premium import FakeProvider
from xtrading.screener.jobs import SessionSkip, run_overnight, run_premarket, run_rth
from xtrading.session import ET

PREMARKET_NOW = datetime(2026, 8, 14, 9, 15, tzinfo=ET)
RTH_NOW = datetime(2026, 8, 14, 9, 30, tzinfo=ET)
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


def test_premarket_is_snapshot_only_no_chains(tmp_path):
    p = DeskProvider()
    folder = run_premarket(
        p,
        filters="f",
        snapshot_root=tmp_path,
        now=lambda: PREMARKET_NOW,
        top_n=3,
    )
    assert any(c.startswith("screener:") for c in p.calls)
    assert not any(c.startswith("history:") for c in p.calls)
    assert not any(c.startswith("chain:") for c in p.calls)
    assert (folder / "snapshot.csv").exists()
    assert not (folder / "ranked.csv").exists()
    assert not (folder / "brief.md").exists()
    meta = (folder / "meta.json").read_text()
    assert "test-token" not in meta
    assert "auth=" not in meta


def test_rth_uses_premarket_snapshot_overnight_rv_and_live_chains(tmp_path):
    p = DeskProvider()
    run_overnight(
        p, filters="f", snapshot_root=tmp_path, now=lambda: OVERNIGHT_NOW, top_n=3,
    )
    run_premarket(
        p, filters="f", snapshot_root=tmp_path, now=lambda: PREMARKET_NOW, top_n=3,
    )
    p.calls.clear()
    folder = run_rth(
        p,
        filters="f",
        snapshot_root=tmp_path,
        now=lambda: RTH_NOW,
        top_n=3,
    )
    assert not any(c.startswith("history:") for c in p.calls)
    assert not any(c.startswith("screener:") for c in p.calls)
    assert any(c.startswith("chain:") for c in p.calls)
    brief = (folder / "brief.md").read_text()
    assert "quote_20d" in brief
    assert "cash is open" in brief.lower()
    assert "BBB" in brief or "no surviving" in brief.lower()
    meta = (folder / "meta.json").read_text()
    assert "test-token" not in meta
    assert "auth=" not in meta
    assert json.loads(meta)["chain_mode"] == "top5"


def test_rth_without_premarket_falls_back_to_screener(tmp_path):
    p = DeskProvider()
    folder = run_rth(
        p, filters="f", snapshot_root=tmp_path, now=lambda: RTH_NOW, top_n=3, force=True,
    )
    assert any(c.startswith("screener:") for c in p.calls)
    assert any(c.startswith("chain:") for c in p.calls)
    brief = (folder / "brief.md").read_text()
    assert "screener_month_vol" in brief


def test_rth_wrong_window_skips():
    with pytest.raises(SessionSkip):
        run_rth(
            DeskProvider(),
            filters="x",
            snapshot_root="unused",
            now=lambda: PREMARKET_NOW,
            top_n=3,
            force=False,
        )


def test_overnight_passes_tickers_to_screener(tmp_path):
    p = DeskProvider()
    run_overnight(
        p,
        filters="sh_opt_option",
        snapshot_root=tmp_path,
        now=lambda: OVERNIGHT_NOW,
        top_n=3,
        tickers=["BBB", "CCC"],
    )
    assert any(c.startswith("screener:sh_opt_option:BBB,CCC") for c in p.calls)


def test_rth_default_chain_n_is_five():
    from xtrading.screener.jobs import RTH_CHAIN_N
    from xtrading.screener.put_premium import ASSUMPTIONS
    assert RTH_CHAIN_N == 5
    assert ASSUMPTIONS["top_n"] == 5


def test_rth_all_watchlist_writes_rth_full_and_leaves_rth_alone(tmp_path):
    p = DeskProvider()
    run_overnight(
        p, filters="f", snapshot_root=tmp_path, now=lambda: OVERNIGHT_NOW, top_n=3,
    )
    run_premarket(
        p, filters="f", snapshot_root=tmp_path, now=lambda: PREMARKET_NOW, top_n=3,
    )
    p.calls.clear()
    folder = run_rth(
        p, filters="f", snapshot_root=tmp_path, now=lambda: RTH_NOW, all_watchlist=True,
    )
    assert folder.name == "rth-full"
    assert (folder / "brief.md").exists()
    meta = json.loads((folder / "meta.json").read_text())
    assert meta["chain_mode"] == "all_watchlist"
    assert not (tmp_path / "2026-08-14" / "rth").exists()
    chained = {c.split(":")[1] for c in p.calls if c.startswith("chain:")}
    assert chained == {"AAA", "BBB", "CCC", "DDD", "EEE"}


def test_all_watchlist_rejected_on_overnight():
    from xtrading.screener.__main__ import main
    assert main(["overnight", "--all-watchlist"]) == 2


def test_premarket_already_wrote_skips_without_finviz(tmp_path):
    p = DeskProvider()
    run_premarket(p, filters="f", snapshot_root=tmp_path, now=lambda: PREMARKET_NOW)
    p.calls.clear()
    with pytest.raises(SessionSkip, match="already wrote"):
        run_premarket(p, filters="f", snapshot_root=tmp_path, now=lambda: PREMARKET_NOW)
    assert p.calls == []


def test_overnight_already_wrote_skips_without_finviz(tmp_path):
    p = DeskProvider()
    run_overnight(p, filters="f", snapshot_root=tmp_path, now=lambda: OVERNIGHT_NOW, top_n=3)
    p.calls.clear()
    with pytest.raises(SessionSkip, match="already wrote"):
        run_overnight(p, filters="f", snapshot_root=tmp_path, now=lambda: OVERNIGHT_NOW, top_n=3)
    assert p.calls == []


def test_rth_already_wrote_skips_without_finviz(tmp_path):
    p = DeskProvider()
    run_overnight(p, filters="f", snapshot_root=tmp_path, now=lambda: OVERNIGHT_NOW, top_n=3)
    run_premarket(p, filters="f", snapshot_root=tmp_path, now=lambda: PREMARKET_NOW, top_n=3)
    run_rth(p, filters="f", snapshot_root=tmp_path, now=lambda: RTH_NOW, top_n=3)
    p.calls.clear()
    with pytest.raises(SessionSkip, match="already wrote"):
        run_rth(p, filters="f", snapshot_root=tmp_path, now=lambda: RTH_NOW, top_n=3)
    assert p.calls == []


def test_rth_partial_ranked_without_brief_runs_again(tmp_path):
    p = DeskProvider()
    day = tmp_path / "2026-08-14" / "rth"
    day.mkdir(parents=True)
    (day / "ranked.csv").write_text("ticker\nAAA\n")
    run_rth(p, filters="f", snapshot_root=tmp_path, now=lambda: RTH_NOW, top_n=3, force=True)
    assert (day / "brief.md").exists()
    assert any(c.startswith("chain:") for c in p.calls)


def test_force_reruns_even_when_done_file_exists(tmp_path):
    p = DeskProvider()
    run_premarket(p, filters="f", snapshot_root=tmp_path, now=lambda: PREMARKET_NOW)
    p.calls.clear()
    run_premarket(p, filters="f", snapshot_root=tmp_path, now=lambda: PREMARKET_NOW, force=True)
    assert any(c.startswith("screener:") for c in p.calls)


def test_rth_all_watchlist_ignores_existing_rth_brief(tmp_path):
    p = DeskProvider()
    run_overnight(p, filters="f", snapshot_root=tmp_path, now=lambda: OVERNIGHT_NOW, top_n=3)
    run_premarket(p, filters="f", snapshot_root=tmp_path, now=lambda: PREMARKET_NOW, top_n=3)
    run_rth(p, filters="f", snapshot_root=tmp_path, now=lambda: RTH_NOW, top_n=3)
    p.calls.clear()
    folder = run_rth(p, filters="f", snapshot_root=tmp_path, now=lambda: RTH_NOW, all_watchlist=True)
    assert folder.name == "rth-full"
    assert any(c.startswith("chain:") for c in p.calls)


def test_overnight_empty_watchlist_is_empty_universe(tmp_path):
    p = DeskProvider()
    folder = run_overnight(
        p,
        filters="sh_opt_option",
        snapshot_root=tmp_path,
        now=lambda: OVERNIGHT_NOW,
        tickers=[],
    )
    meta = json.loads((folder / "meta.json").read_text())
    assert meta["empty_universe"] is True
    assert not any(c.startswith("screener:") for c in p.calls)
    assert not any(c.startswith("history:") for c in p.calls)

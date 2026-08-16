"""Scheduled overnight RV, 9:00 Gap prelayer, and 9:30 RTH put-premium jobs."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

import pandas as pd

from xtrading.screener.brief import format_brief
from xtrading.screener.put_premium import (
    PREMARKET_COLUMNS,
    STAGE1_COLUMNS,
    STAGE1_VIEW,
    PutPremiumScreener,
    _normalize_universe,
    realized_vol,
    stage1_top_tickers,
)
from xtrading.screener.snapshots import SnapshotStore
from xtrading.session import et_date, job_for

DEFAULT_FILTERS = "sh_opt_option"
OVERNIGHT_TOP_N = 20  # Finviz /export/quote 60s budget, not a product cap
RTH_CHAIN_N = 5


class SessionSkip(RuntimeError):
    """Wrong ET window, already wrote today's snapshot, and force was not set."""


_DONE_FILE = {
    "overnight": ("overnight", "rv.json"),
    "premarket": ("premarket", "snapshot.csv"),
    "rth": ("rth", "brief.md"),
}


def _require(job: str, now: Callable[[], datetime], force: bool) -> None:
    actual = job_for(now())
    if force:
        return
    if actual != job:
        raise SessionSkip(f"session is {actual!r}, need {job!r} (pass force=True to override)")


def _refuse_if_wrote(
    job: str,
    snapshot_root: Path | str,
    now: Callable[[], datetime],
    force: bool,
    *,
    all_watchlist: bool = False,
) -> None:
    if force or all_watchlist:
        return
    spec = _DONE_FILE.get(job)
    if spec is None:
        return
    sub, name = spec
    path = SnapshotStore(snapshot_root).day_dir(et_date(now())) / sub / name
    if path.exists():
        raise SessionSkip(f"already wrote {path}")


def _retry_once(fn):
    try:
        return fn()
    except Exception:
        return fn()


def _empty_watchlist(tickers: list[str] | None) -> bool:
    return tickers is not None and len(tickers) == 0


def run_overnight(
    provider,
    *,
    filters: str,
    snapshot_root: Path | str,
    now: Callable[[], datetime],
    top_n: int = OVERNIGHT_TOP_N,
    force: bool = False,
    tickers: list[str] | None = None,
) -> Path:
    _require("overnight", now, force)
    _refuse_if_wrote("overnight", snapshot_root, now, force)
    today = et_date(now())
    store = SnapshotStore(snapshot_root)
    if _empty_watchlist(tickers):
        meta = {
            "fetched_at": now().isoformat(),
            "job": "overnight",
            "tickers": [],
            "n_export_calls": 0,
            "empty_universe": True,
            "errors": [],
            "rv_source": "quote_20d",
        }
        return store.write_overnight(today, universe=pd.DataFrame(), rv={}, meta=meta)
    print(f"Overnight job {today.isoformat()}: 1 screener + {top_n} /export/quote (60s each)")
    raw = _retry_once(lambda: provider.fetch_screener(
        filters, view=STAGE1_VIEW, columns=STAGE1_COLUMNS, tickers=tickers,
    ))
    universe = _normalize_universe(raw)
    hist_tickers = stage1_top_tickers(universe, n=top_n)
    fetch_hist = getattr(provider, "fetch_history", None)
    if fetch_hist is None:
        raise RuntimeError("provider has no fetch_history")
    rv: dict[str, float] = {}
    errors: list[str] = []
    for t in hist_tickers:
        try:
            closes = _retry_once(lambda ticker=t: fetch_hist(ticker))
            rv[t] = realized_vol(closes)
        except Exception as exc:
            errors.append(f"{t}: {exc}")
    meta = {
        "fetched_at": now().isoformat(),
        "job": "overnight",
        "tickers": hist_tickers,
        "n_export_calls": 1 + len(rv),
        "empty_universe": universe.empty,
        "errors": errors,
        "rv_source": "quote_20d",
    }
    return store.write_overnight(today, universe=universe, rv=rv, meta=meta)


def run_premarket(
    provider,
    *,
    filters: str,
    snapshot_root: Path | str,
    now: Callable[[], datetime],
    top_n: int = RTH_CHAIN_N,
    force: bool = False,
    tickers: list[str] | None = None,
) -> Path:
    _require("premarket", now, force)
    _refuse_if_wrote("premarket", snapshot_root, now, force)
    today = et_date(now())
    store = SnapshotStore(snapshot_root)
    if _empty_watchlist(tickers):
        meta = {
            "fetched_at": now().isoformat(),
            "job": "premarket",
            "empty_universe": True,
            "errors": [],
            "n_export_calls": 0,
        }
        return store.write_premarket(today, snapshot=pd.DataFrame(), meta=meta)
    print(f"Premarket job {today.isoformat()}: 1 Gap screener, no chains")
    raw = _retry_once(lambda: provider.fetch_screener(
        filters, view=STAGE1_VIEW, columns=PREMARKET_COLUMNS, tickers=tickers,
    ))
    empty = raw.empty if hasattr(raw, "empty") else False
    meta = {
        "fetched_at": now().isoformat(),
        "job": "premarket",
        "empty_universe": bool(empty),
        "errors": [],
        "n_export_calls": 1,
    }
    return store.write_premarket(today, snapshot=raw, meta=meta)


def _rv_source(ranked, rv: dict) -> str:
    if not rv:
        return "screener_month_vol"
    used = set(ranked["ticker"].astype(str)) if not ranked.empty else set()
    if used and not used.issubset(set(rv)):
        return "mixed"
    return "quote_20d"


def run_rth(
    provider,
    *,
    filters: str,
    snapshot_root: Path | str,
    now: Callable[[], datetime],
    top_n: int = RTH_CHAIN_N,
    force: bool = False,
    tickers: list[str] | None = None,
    all_watchlist: bool = False,
) -> Path:
    _require("rth", now, force)
    _refuse_if_wrote("rth", snapshot_root, now, force, all_watchlist=all_watchlist)
    today = et_date(now())
    store = SnapshotStore(snapshot_root)
    chain_mode = "all_watchlist" if all_watchlist else "top5"
    job_name = "rth-full" if all_watchlist else "rth"
    if _empty_watchlist(tickers):
        meta = {
            "fetched_at": now().isoformat(),
            "job": job_name,
            "rv_from": None,
            "rv_source": "none",
            "empty_universe": True,
            "errors": [],
            "n_export_calls": 0,
            "prelayer": "none",
            "chain_mode": chain_mode,
        }
        brief = format_brief(pd.DataFrame(), pd.DataFrame(), meta)
        return store.write_rth(
            today, ranked=pd.DataFrame(), brief=brief, meta=meta, job=job_name,
        )
    raw = store.load_premarket_snapshot(today)
    n_exports = 0
    if raw is None:
        print(f"RTH job {today.isoformat()}: missing prelayer, 1 Gap screener then options JSON")
        raw = _retry_once(lambda: provider.fetch_screener(
            filters, view=STAGE1_VIEW, columns=PREMARKET_COLUMNS, tickers=tickers,
        ))
        n_exports = 1
    else:
        print(f"RTH job {today.isoformat()}: using 9:00 snapshot, options JSON (unthrottled)")
    rv_date, rv = store.load_latest_rv(before=today)
    ranked = PutPremiumScreener(provider, now=now).run(
        filters=filters,
        top_n=top_n,
        columns=PREMARKET_COLUMNS,
        screener_df=raw,
        pull_history=False,
        rv_override=rv or None,
        tickers=tickers,
        all_watchlist=all_watchlist,
    )
    empty = raw.empty if hasattr(raw, "empty") else False
    chain_mode = "all_watchlist" if all_watchlist else "top5"
    meta = {
        "fetched_at": now().isoformat(),
        "job": "rth-full" if all_watchlist else "rth",
        "rv_from": rv_date.isoformat() if rv_date else None,
        "rv_source": _rv_source(ranked, rv),
        "empty_universe": bool(empty),
        "errors": [],
        "n_export_calls": n_exports,
        "prelayer": "snapshot" if n_exports == 0 else "screener_fallback",
        "chain_mode": chain_mode,
    }
    brief = format_brief(ranked, raw, meta)
    return store.write_rth(
        today,
        ranked=ranked,
        brief=brief,
        meta=meta,
        job="rth-full" if all_watchlist else "rth",
    )

"""Scheduled overnight RV and premarket put-premium jobs."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

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

DEFAULT_FILTERS = "sh_opt_option,sh_avgvol_o400,sh_price_o10"
OVERNIGHT_TOP_N = 20
PREMARKET_CHAIN_N = 3


class SessionSkip(RuntimeError):
    """Wrong ET window and force was not set."""


def _require(job: str, now: Callable[[], datetime], force: bool) -> None:
    actual = job_for(now())
    if force:
        return
    if actual != job:
        raise SessionSkip(f"session is {actual!r}, need {job!r} (pass force=True to override)")


def _retry_once(fn):
    try:
        return fn()
    except Exception:
        return fn()


def run_overnight(
    provider,
    *,
    filters: str,
    snapshot_root: Path | str,
    now: Callable[[], datetime],
    top_n: int = OVERNIGHT_TOP_N,
    force: bool = False,
) -> Path:
    _require("overnight", now, force)
    today = et_date(now())
    print(f"Overnight job {today.isoformat()}: 1 screener + {top_n} /export/quote (60s each)")
    raw = _retry_once(lambda: provider.fetch_screener(
        filters, view=STAGE1_VIEW, columns=STAGE1_COLUMNS,
    ))
    universe = _normalize_universe(raw)
    tickers = stage1_top_tickers(universe, n=top_n)
    fetch_hist = getattr(provider, "fetch_history", None)
    if fetch_hist is None:
        raise RuntimeError("provider has no fetch_history")
    rv: dict[str, float] = {}
    errors: list[str] = []
    for t in tickers:
        try:
            closes = _retry_once(lambda ticker=t: fetch_hist(ticker))
            rv[t] = realized_vol(closes)
        except Exception as exc:
            errors.append(f"{t}: {exc}")
    store = SnapshotStore(snapshot_root)
    meta = {
        "fetched_at": now().isoformat(),
        "job": "overnight",
        "tickers": tickers,
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
    top_n: int = PREMARKET_CHAIN_N,
    force: bool = False,
) -> Path:
    _require("premarket", now, force)
    today = et_date(now())
    print(f"Premarket job {today.isoformat()}: 1 Gap screener, then options JSON (unthrottled)")
    raw = _retry_once(lambda: provider.fetch_screener(
        filters, view=STAGE1_VIEW, columns=PREMARKET_COLUMNS,
    ))
    store = SnapshotStore(snapshot_root)
    rv_date, rv = store.load_latest_rv(before=today)
    ranked = PutPremiumScreener(provider, now=now).run(
        filters=filters,
        top_n=top_n,
        columns=PREMARKET_COLUMNS,
        screener_df=raw,
        pull_history=False,
        rv_override=rv or None,
    )
    if rv:
        used = set(ranked["ticker"].astype(str)) if not ranked.empty else set()
        if used and not used.issubset(set(rv)):
            rv_source = "mixed"
        else:
            rv_source = "quote_20d"
    else:
        rv_source = "screener_month_vol"
    empty = raw.empty if hasattr(raw, "empty") else False
    meta = {
        "fetched_at": now().isoformat(),
        "job": "premarket",
        "rv_from": rv_date.isoformat() if rv_date else None,
        "rv_source": rv_source,
        "empty_universe": bool(empty),
        "errors": [],
        "n_export_calls": 1,
    }
    brief = format_brief(ranked, raw, meta)
    return store.write_premarket(
        today, snapshot=raw, ranked=ranked, brief=brief, meta=meta,
    )

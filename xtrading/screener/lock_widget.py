"""Lock-screen widget payload: the six loudest overnight RVs.

Two accessory-rectangular widgets (left 1–3, right 4–6). iOS tints lock-screen
widgets, so heat is a three-step tone, not a color scale. Tap opens a GitHub
markdown tape in Safari — not the Claude app composer (keyboard covers Send).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

import pandas as pd

EARN_HORIZON_DAYS = 14
HOT_N = 6
TAPE_PATH = "snapshots/lock-tape.md"
TAPE_URL = f"https://github.com/denysyarin/options-desk/blob/main/{TAPE_PATH}"
BAR_WIDTH = 10


def _heat(rv: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.0
    return (rv - lo) / (hi - lo)


def _tone(rv: float, lo: float, hi: float) -> str:
    t = _heat(rv, lo, hi)
    if t >= 0.7:
        return "hot"
    if t >= 0.38:
        return "mid"
    return "cold"


def _earn_soon(raw, as_of: date) -> bool:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return False
    if isinstance(raw, date) and not isinstance(raw, pd.Timestamp):
        earn = raw
    else:
        parsed = pd.to_datetime(raw, errors="coerce")
        if pd.isna(parsed):
            return False
        earn = parsed.date()
    return as_of <= earn <= as_of + timedelta(days=EARN_HORIZON_DAYS)


def build_lock_widget(
    rv: dict[str, float],
    *,
    as_of: date,
    fetched_at: str = "",
    earnings: dict[str, object] | None = None,
    month_vol: dict[str, float] | None = None,
    order: Iterable[str] | None = None,
) -> dict:
    earnings = earnings or {}
    month_vol = month_vol or {}
    names = [str(t).upper() for t in (order or rv.keys()) if str(t).upper() in rv]
    if not names:
        names = [str(t).upper() for t in rv]
    vals = [float(rv[t]) for t in names] or [0.0]
    lo, hi = min(vals), max(vals)
    ranked = sorted(names, key=lambda t: float(rv[t]), reverse=True)[:HOT_N]
    hot = []
    for t in ranked:
        row = {
            "ticker": t,
            "rv": round(float(rv[t]), 3),
            "tone": _tone(float(rv[t]), lo, hi),
            "earn": _earn_soon(earnings.get(t), as_of),
        }
        if t in month_vol:
            row["month_vol"] = round(float(month_vol[t]), 3)
        hot.append(row)
    payload = {
        "as_of": as_of.isoformat(),
        "fetched_at": fetched_at,
        "label": "RV",
        "hot": hot,
    }
    payload["click_url"] = lock_click_url(payload)
    return payload


def _bars(rv: float, top: float) -> str:
    if top <= 0:
        return ""
    n = max(1, min(BAR_WIDTH, round(BAR_WIDTH * rv / top)))
    return "█" * n


def lock_tape_markdown(payload: dict) -> str:
    """Deterministic RV tape. Python already has the numbers; no model, no keyboard."""
    hot = list(payload.get("hot") or [])
    as_of = payload.get("as_of") or ""
    top = float(hot[0]["rv"]) if hot else 0.0
    lines = [
        f"# RV tape — {as_of}",
        "",
        "Not a LOOK list. No option chains yet.",
        "",
        "| # | Ticker | 20d RV | vs #1 | Month vol | Earn |",
        "|---|---|---|---|---|---|",
    ]
    with_month = []
    earn_names = []
    for i, row in enumerate(hot, 1):
        rv = float(row["rv"])
        month = row.get("month_vol")
        month_s = f"{float(month):.2f}" if month is not None else "—"
        earn = "soon" if row.get("earn") else ""
        if month is not None:
            with_month.append((str(row["ticker"]), float(month)))
        if row.get("earn"):
            earn_names.append(str(row["ticker"]))
        lines.append(
            f"| {i} | {row['ticker']} | {rv:.2f} | {_bars(rv, top)} | {month_s} | {earn} |"
        )
    with_month.sort(key=lambda x: x[1], reverse=True)
    both = [t for t, _ in with_month[:3]] if with_month else []
    both_s = ", ".join(both) if both else "none"
    earn_s = ", ".join(earn_names) if earn_names else "none"
    lines.extend(
        [
            "",
            f"**Toward 09:30** — Loud on both tapes: {both_s}. "
            f"Earnings-risky: {earn_s}. Wait for `snapshots/{as_of}/rth/brief.md`. "
            "This is not a LOOK list.",
            "",
        ]
    )
    return "\n".join(lines)


def lock_click_url(payload: dict | None = None, *, repo: str = "denysyarin/options-desk") -> str:
    """Tap opens the pre-rendered tape in Safari. Claude's composer is unusable on iOS."""
    return TAPE_URL


def earnings_from_universe(universe: pd.DataFrame) -> dict[str, object]:
    if universe is None or universe.empty:
        return {}
    ticker_col = "Ticker" if "Ticker" in universe.columns else "ticker"
    earn_col = "earnings_date" if "earnings_date" in universe.columns else None
    if earn_col is None:
        return {}
    out: dict[str, object] = {}
    for _, row in universe.iterrows():
        out[str(row[ticker_col]).upper()] = row[earn_col]
    return out


def month_vol_from_universe(universe: pd.DataFrame) -> dict[str, float]:
    if universe is None or universe.empty:
        return {}
    ticker_col = "Ticker" if "Ticker" in universe.columns else "ticker"
    if "range_vol_ann" not in universe.columns:
        return {}
    out: dict[str, float] = {}
    for _, row in universe.iterrows():
        raw = row["range_vol_ann"]
        if raw is None or (isinstance(raw, float) and pd.isna(raw)):
            continue
        out[str(row[ticker_col]).upper()] = float(raw)
    return out

"""Deterministic markdown brief. Numbers come from Python, not a model."""
from __future__ import annotations

import pandas as pd


def format_brief(
    ranked: pd.DataFrame,
    snapshot: pd.DataFrame,
    meta: dict,
) -> str:
    fetched = meta.get("fetched_at", "")
    rv_source = meta.get("rv_source", "unknown")
    job = meta.get("job", "rth")
    if job == "premarket":
        tape = "This is the 9:00 prelayer. Gap is live until 9:30 ET. Not a trade list."
    elif job == "rth":
        tape = "Cash is open. Chains are live. Gap is frozen from the 9:00 prelayer."
    else:
        tape = "Gap freezes at the 9:30 ET cash open; treat this snapshot as stale after that."
    lines = [
        f"# Options desk brief",
        f"",
        f"As of {fetched} (America/New_York).",
        f"RV source: `{rv_source}`.",
        f"",
        f"Not financial advice. {tape}",
        f"Rank is VRP, then annualized RoC, then spread — never raw premium.",
        f"",
    ]
    if meta.get("empty_universe"):
        lines.append("Universe is empty. No liquid names this session.")
        return "\n".join(lines) + "\n"

    gap_by = {}
    if not snapshot.empty and "Ticker" in snapshot.columns:
        gap_col = "Gap" if "Gap" in snapshot.columns else None
        for _, row in snapshot.iterrows():
            gap_by[str(row["Ticker"]).upper()] = row[gap_col] if gap_col else ""

    if ranked is None or ranked.empty:
        lines.append("No surviving cash-secured puts after hard filters.")
        return "\n".join(lines) + "\n"

    lines.append(
        "| ticker | strike | DTE | mid | basis | RoC | delta | IV | 20d RV | VRP | Gap | flags |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for _, row in ranked.iterrows():
        ticker = str(row["ticker"]).upper()
        gap = gap_by.get(ticker, "")
        flags = []
        if bool(row.get("iv_unreliable", False)):
            flags.append("unreliable_IV")
        strike = float(row["strike"])
        mid = float(row["mid"])
        if "basis" in row.index and pd.notna(row["basis"]):
            basis = float(row["basis"])
        elif "breakeven" in row.index and pd.notna(row["breakeven"]):
            basis = float(row["breakeven"])
        else:
            basis = strike - mid
        roc = float(row["annualized_roc"]) if "annualized_roc" in row.index else float("nan")
        lines.append(
            "| {ticker} | {strike:.2f} | {dte} | {mid:.2f} | {basis:.2f} | {roc:.3f} | "
            "{delta:.3f} | {iv:.3f} | {rv:.3f} | {vrp:.3f} | {gap} | {flags} |".format(
                ticker=ticker,
                strike=strike,
                dte=int(row["dte"]),
                mid=mid,
                basis=basis,
                roc=roc,
                delta=float(row["delta"]),
                iv=float(row["iv"]),
                rv=float(row["rv_20d"]),
                vrp=float(row["vrp"]),
                gap=gap,
                flags=",".join(flags) or "",
            )
        )
    return "\n".join(lines) + "\n"

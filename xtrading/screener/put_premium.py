"""Put-premium screener on top of ``OptionScreener``.

Stage 1 is a single Finviz screener export. Stage 2 is option-chain
exports for the top 3 names only, and only for Friday expiries in 2–9 DTE.
The call plan and ETA are printed before any network call.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Callable, Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from xtrading.data.base import ChainProvider, FetchJob, FetchPlan, OptionChain
from xtrading.skills.options import OptionScreener

ET = ZoneInfo("America/New_York")

ASSUMPTIONS = {
    "r": 0.05,
    "rv_window": 20,
    "annualization_days": 365,
    "rv_annualization": 252,
    "contract_multiplier": 100,
    "min_dte": 2,
    "max_dte": 9,
    "top_n": 3,
    "min_abs_delta": 0.10,
    "max_abs_delta": 0.25,
    "min_open_interest": 500,
    "min_volume": 100,
    "max_spread": 0.15,
    "max_quote_age": timedelta(minutes=5),
    "cheap_quote": 0.10,
}

_IV_COLS = ("iv_proxy", "Implied Volatility", "IV", "Volatility")
_VOL_COLS = ("avg_volume", "Avg Volume", "Average Volume", "Volume")
_PRICE_COLS = ("Price", "price")
_EARN_COLS = ("earnings_date", "Earnings Date", "Earnings")


def realized_vol(closes: pd.Series, window: int = 20) -> float:
    logret = np.log(closes.astype(float) / closes.astype(float).shift(1)).dropna()
    window_rets = logret.iloc[-window:]
    if len(window_rets) < window:
        raise ValueError(f"need {window} log returns to compute realized vol, got {len(window_rets)}")
    return float(window_rets.std(ddof=1) * np.sqrt(ASSUMPTIONS["rv_annualization"]))


def expiries_in_window(today: date, min_dte: int = 2, max_dte: int = 9) -> list[date]:
    out = []
    for dte in range(min_dte, max_dte + 1):
        d = today + timedelta(days=dte)
        if d.weekday() == 4:
            out.append(d)
    return out


def stage1_top_tickers(df: pd.DataFrame, n: int = 3) -> list[str]:
    universe = _normalize_universe(df)
    ranked = universe.sort_values(["iv_proxy", "avg_volume"], ascending=[False, False])
    return [str(t) for t in ranked["Ticker"].head(n).tolist()]


def _first_col(df: pd.DataFrame, names: tuple[str, ...]) -> Optional[str]:
    for name in names:
        if name in df.columns:
            return name
    lower = {c.lower(): c for c in df.columns}
    for name in names:
        if name.lower() in lower:
            return lower[name.lower()]
    return None


def _parse_earnings(value) -> Optional[date]:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "-"}:
        return None
    text = text.replace("AMC", "").replace("BMO", "").strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%b %d %Y", "%b %d"):
        try:
            parsed = datetime.strptime(text, fmt)
            if parsed.year == 1900:
                parsed = parsed.replace(year=datetime.now(tz=ET).year)
            return parsed.date()
        except ValueError:
            continue
    return None


def _normalize_universe(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame()
    ticker_col = _first_col(df, ("Ticker", "ticker"))
    if ticker_col is None:
        raise ValueError("screener export missing Ticker")
    out["Ticker"] = df[ticker_col].astype(str).str.upper()
    price_col = _first_col(df, _PRICE_COLS)
    iv_col = _first_col(df, _IV_COLS)
    vol_col = _first_col(df, _VOL_COLS)
    earn_col = _first_col(df, _EARN_COLS)
    out["Price"] = pd.to_numeric(df[price_col], errors="coerce") if price_col else np.nan
    iv = pd.to_numeric(df[iv_col], errors="coerce") if iv_col else np.nan
    # Finviz sometimes ships IV as percent (25.3) rather than 0.253
    if isinstance(iv, pd.Series) and iv.dropna().gt(3).mean() > 0.5:
        iv = iv / 100.0
    out["iv_proxy"] = iv
    out["avg_volume"] = pd.to_numeric(df[vol_col], errors="coerce") if vol_col else np.nan
    out["earnings_date"] = df[earn_col].map(_parse_earnings) if earn_col else None
    return out.dropna(subset=["Ticker", "iv_proxy"])


def format_plan(plan: FetchPlan) -> str:
    lines = ["Call plan", "Stage 1: 1 screener export for the full universe"]
    stage2 = [j for j in plan.jobs if j.ticker != "SCREENER"]
    if stage2:
        lines.append("Stage 2: chain exports (top 3 × 2–9 DTE Fridays)")
        for job in stage2:
            lines.append(f"  - {job.ticker} {job.expiry.isoformat()}")
    else:
        lines.append("Stage 2: up to 3 tickers × Friday expiries in 2–9 DTE")
    minutes = plan.eta.total_seconds() / 60.0
    lines.append(
        f"Network calls: {plan.n_network_calls}  "
        f"ETA: {minutes:.0f} min ({int(plan.eta.total_seconds())}s)  "
        f"cache hits: {plan.n_cache_hits}"
    )
    lines.append("Finviz limit: 1 export / 60s")
    return "\n".join(lines)


def hard_filter_rows(df: pd.DataFrame, *, today: date) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    rows = []
    for _, row in df.iterrows():
        dte = int(row["dte"])
        expiry = today + timedelta(days=dte)
        earn = row.get("earnings_date")
        if pd.notna(earn) and earn is not None and today <= earn <= expiry:
            continue
        if row["open_interest"] < ASSUMPTIONS["min_open_interest"]:
            continue
        if row["volume"] < ASSUMPTIONS["min_volume"]:
            continue
        mid = row["mid"]
        if mid is None or mid <= 0:
            continue
        spread = (row["ask"] - row["bid"]) / mid
        if spread > ASSUMPTIONS["max_spread"]:
            continue
        age = row.get("quote_age")
        if age is None or pd.isna(age) or age > ASSUMPTIONS["max_quote_age"]:
            continue
        abs_delta = abs(float(row["delta"]))
        if not (ASSUMPTIONS["min_abs_delta"] <= abs_delta <= ASSUMPTIONS["max_abs_delta"]):
            continue
        rec = dict(row)
        rec["spread"] = spread
        rec["iv_unreliable"] = bool(row.get("iv_unreliable", False)) or mid < ASSUMPTIONS["cheap_quote"]
        rows.append(rec)
    return pd.DataFrame(rows)


def rank_rows(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    out = df.copy()
    if "vrp" not in out.columns:
        out["vrp"] = out["iv"] - out["rv_20d"]
    if "annualized_roc" not in out.columns:
        out["annualized_roc"] = (out["mid"] / out["strike"]) * (
            ASSUMPTIONS["annualization_days"] / out["dte"]
        )
    if "spread_pct" not in out.columns:
        if "spread" in out.columns:
            out["spread_pct"] = out["spread"]
        else:
            out["spread_pct"] = (out["ask"] - out["bid"]) / out["mid"]
    if "capital" not in out.columns:
        out["capital"] = out["strike"] * ASSUMPTIONS["contract_multiplier"]
    if "breakeven" not in out.columns:
        out["breakeven"] = out["strike"] - out["mid"]
    if "quote_time" not in out.columns and "last_trade" in out.columns:
        out["quote_time"] = out["last_trade"]
    if "iv_unreliable" not in out.columns:
        out["iv_unreliable"] = out["mid"] < ASSUMPTIONS["cheap_quote"]
    else:
        out["iv_unreliable"] = out["iv_unreliable"] | (out["mid"] < ASSUMPTIONS["cheap_quote"])
    return out.sort_values(
        ["vrp", "annualized_roc", "spread_pct"],
        ascending=[False, False, True],
    ).reset_index(drop=True)


def format_table(df: pd.DataFrame) -> str:
    a = ASSUMPTIONS
    header = (
        f"Assumptions: rate r={a['r']}, RV window={a['rv_window']} trading days "
        f"(annualized √{a['rv_annualization']}), RoC annualized on {a['annualization_days']}-day year, "
        f"cash-secured put capital = strike × {a['contract_multiplier']}. "
        f"Never rank by raw premium. "
        f"IV from a quote mid < ${a['cheap_quote']:.2f} is flagged unreliable."
    )
    if df.empty:
        return header + "\n(no surviving puts)\n"
    show = pd.DataFrame({
        "ticker": df["ticker"],
        "strike": df["strike"].map(lambda x: f"{x:.2f}"),
        "DTE": df["dte"],
        "bid": df["bid"].map(lambda x: f"{x:.2f}"),
        "ask": df["ask"].map(lambda x: f"{x:.2f}"),
        "mid": df["mid"].map(lambda x: f"{x:.2f}"),
        "delta": df["delta"].map(lambda x: f"{x:.3f}"),
        "IV": df["iv"].map(lambda x: f"{x:.3f}"),
        "20d RV": df["rv_20d"].map(lambda x: f"{x:.3f}"),
        "VRP": df["vrp"].map(lambda x: f"{x:.3f}"),
        "annualized RoC": df["annualized_roc"].map(lambda x: f"{x:.3f}"),
        "spread %": (df["spread_pct"] * 100).map(lambda x: f"{x:.1f}"),
        "capital": df["capital"].map(lambda x: f"{x:.0f}"),
        "breakeven": df["breakeven"].map(lambda x: f"{x:.2f}"),
        "timestamp": df["quote_time"].astype(str),
        "unreliable_IV": df["iv_unreliable"].map(lambda x: "FLAG" if x else ""),
    })
    return header + "\n" + show.to_string(index=False) + "\n"


def _quotes_to_screener_frame(chain: OptionChain, today: date) -> pd.DataFrame:
    rows = []
    dte = (chain.expiry - today).days
    for q in chain.quotes:
        if q.option_type != "put" or q.iv is None:
            continue
        rows.append({
            "strike": q.strike,
            "expiry_days": dte,
            "iv": q.iv,
            "bid": q.bid,
            "ask": q.ask,
            "mid": q.mid,
            "volume": q.volume,
            "open_interest": q.open_interest,
            "quote_age": q.quote_age,
            "last_trade": q.last_trade,
            "iv_unreliable": q.iv_unreliable,
            "ticker": q.ticker or chain.ticker,
        })
    return pd.DataFrame(rows)


class PutPremiumScreener:
    def __init__(
        self,
        provider: ChainProvider,
        *,
        now: Optional[Callable[[], datetime]] = None,
        r: float = ASSUMPTIONS["r"],
    ):
        self.provider = provider
        self._now = now or (lambda: datetime.now(tz=ET))
        self.r = r

    def run(
        self,
        *,
        filters: str,
        history: dict[str, pd.Series],
        top_n: int = ASSUMPTIONS["top_n"],
    ) -> pd.DataFrame:
        today = self._now().astimezone(ET).date()
        expiries = expiries_in_window(
            today, ASSUMPTIONS["min_dte"], ASSUMPTIONS["max_dte"]
        )
        n_stage2_slots = top_n * max(len(expiries), 1)
        upper = FetchPlan(
            n_network_calls=1 + n_stage2_slots,
            n_cache_hits=0,
            eta=timedelta(seconds=(1 + n_stage2_slots - 1) * 60),
            jobs=[FetchJob("SCREENER", date.min)]
            + [FetchJob(f"TOP{i}", expiries[0] if expiries else today) for i in range(top_n)],
        )
        print(format_plan(upper))
        print()

        raw = self.provider.fetch_screener(filters)
        universe = _normalize_universe(raw)
        tickers = stage1_top_tickers(universe, n=top_n)
        earnings = {
            str(r.Ticker): r.earnings_date
            for r in universe.itertuples(index=False)
        }
        spots = {
            str(r.Ticker): float(r.Price)
            for r in universe.itertuples(index=False)
            if pd.notna(r.Price)
        }

        jobs = [FetchJob(t, e) for t in tickers for e in expiries]
        plan = self.provider.dry_run(jobs) if jobs else FetchPlan(0, 0, timedelta(0), [])
        # dry_run counts only chain jobs; add the screener call already spent
        print(format_plan(FetchPlan(
            n_network_calls=plan.n_network_calls,
            n_cache_hits=plan.n_cache_hits,
            eta=plan.eta,
            jobs=jobs,
        )))
        print()

        candidates = []
        for job in jobs:
            try:
                chain = self.provider.fetch_chain(
                    job.ticker,
                    job.expiry,
                    spot=spots.get(job.ticker),
                    max_age=timedelta(days=365),
                    r=self.r,
                    enforce_stale=False,
                )
            except TypeError:
                chain = self.provider.fetch_chain(
                    job.ticker,
                    job.expiry,
                    spot=spots.get(job.ticker),
                    max_age=timedelta(days=365),
                    r=self.r,
                )
            except ValueError:
                continue
            frame = _quotes_to_screener_frame(chain, today)
            if frame.empty:
                continue
            screened = OptionScreener(
                frame[["strike", "expiry_days", "iv"]],
                underlying_price=chain.spot,
                r=self.r,
            ).screen(
                min_dte=ASSUMPTIONS["min_dte"],
                max_dte=ASSUMPTIONS["max_dte"],
                min_delta=ASSUMPTIONS["min_abs_delta"],
                max_delta=ASSUMPTIONS["max_abs_delta"],
                option_type="put",
            )
            if screened.empty:
                continue
            merged = screened.merge(frame, on=["strike", "expiry_days", "iv"], how="inner")
            try:
                rv = realized_vol(history[job.ticker], window=ASSUMPTIONS["rv_window"])
            except (KeyError, ValueError):
                continue
            for _, row in merged.iterrows():
                candidates.append({
                    "ticker": row["ticker"],
                    "strike": row["strike"],
                    "dte": int(row["expiry_days"]),
                    "bid": row["bid"],
                    "ask": row["ask"],
                    "mid": row["mid"],
                    "delta": row["delta"],
                    "iv": row["iv"],
                    "rv_20d": rv,
                    "volume": row["volume"],
                    "open_interest": row["open_interest"],
                    "quote_age": row["quote_age"],
                    "last_trade": row["last_trade"],
                    "earnings_date": earnings.get(job.ticker),
                    "spot": chain.spot,
                    "iv_unreliable": bool(row.get("iv_unreliable", False)),
                })

        kept = hard_filter_rows(pd.DataFrame(candidates), today=today)
        ranked = rank_rows(kept)
        print(format_table(ranked))
        return ranked

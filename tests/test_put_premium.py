"""Put-premium screener: filters, ranking, and the two-stage Finviz plan.

No network. Chains and the Stage-1 universe are injected.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from xtrading.data.base import FetchJob, FetchPlan, OptionChain, OptionQuote
from xtrading.screener.put_premium import (
    ASSUMPTIONS,
    expiries_in_window,
    format_plan,
    format_table,
    hard_filter_rows,
    rank_rows,
    realized_vol,
    stage1_top_tickers,
)
from xtrading.screener.put_premium import PutPremiumScreener
from xtrading.skills.options import GreeksCalculator

ET = ZoneInfo("America/New_York")
NOW = datetime(2026, 8, 14, 9, 35, tzinfo=ET)
TODAY = date(2026, 8, 14)
EXPIRY = date(2026, 8, 21)  # 7 DTE, Friday


def _closes(start=100.0, n=21, daily=0.01):
    """n prices → n-1 returns; take the last 20 for RV."""
    rets = np.full(n - 1, daily)
    px = [start]
    for r in rets:
        px.append(px[-1] * np.exp(r))
    return pd.Series(px)


def test_realized_vol_is_std_of_20_log_returns_times_sqrt_252():
    closes = _closes()
    logret = np.log(closes / closes.shift(1)).dropna().iloc[-20:]
    expected = float(logret.std(ddof=1) * np.sqrt(252))
    assert realized_vol(closes, window=20) == pytest.approx(expected)


def test_realized_vol_rejects_short_history():
    with pytest.raises(ValueError, match="20"):
        realized_vol(pd.Series(range(10)), window=20)


def test_stage1_cuts_to_three_by_month_range_vol_then_volume_not_price():
    df = pd.DataFrame({
        "Ticker": ["AAA", "BBB", "CCC", "DDD", "EEE"],
        "Price": [500.0, 10.0, 50.0, 80.0, 20.0],
        "Volatility (Month)": ["2.00%", "8.00%", "7.00%", "7.00%", "1.00%"],
        "Average Volume": [1e6, 2e6, 9e6, 1e6, 9e6],
        "Earnings Date": [None] * 5,
    })
    picked = stage1_top_tickers(df, n=3)
    # BBB highest month-vol; CCC vs DDD tied vol, CCC wins on volume
    assert picked == ["BBB", "CCC", "DDD"]
    assert "AAA" not in picked


def test_stage1_parses_live_finviz_earnings_timestamp():
    df = pd.DataFrame({
        "Ticker": ["MSFT"],
        "Price": [498.07],
        "Volatility (Month)": ["2.80%"],
        "Average Volume": [40732.19],
        "Earnings Date": ["7/29/2026 4:30:00 PM"],
    })
    from xtrading.screener.put_premium import _normalize_universe
    uni = _normalize_universe(df)
    assert uni.iloc[0]["earnings_date"] == date(2026, 7, 29)


def test_expiries_in_2_to_9_dte_are_fridays_only():
    found = expiries_in_window(TODAY, min_dte=2, max_dte=9)
    assert found == [date(2026, 8, 21)]
    assert all(d.weekday() == 4 for d in found)
    assert all(2 <= (d - TODAY).days <= 9 for d in found)


def test_format_plan_states_stage1_then_stage2_and_eta():
    plan = FetchPlan(
        n_network_calls=4,
        n_cache_hits=0,
        eta=timedelta(seconds=180),
        jobs=[
            FetchJob("SCREENER", date.min),
            FetchJob("BBB", EXPIRY),
            FetchJob("CCC", EXPIRY),
            FetchJob("DDD", EXPIRY),
        ],
    )
    text = format_plan(plan)
    assert "Stage 1" in text
    assert "Stage 2" in text
    assert "180" in text or "3m" in text or "3 min" in text
    assert "BBB" in text


def _quote(**kwargs) -> OptionQuote:
    defaults = dict(
        contract="TST260821P00095000",
        ticker="TST",
        expiry=EXPIRY,
        option_type="put",
        strike=95.0,
        last_trade=NOW - timedelta(minutes=1),
        quote_age=timedelta(minutes=1),
        last_close=1.5,
        bid=1.40,
        ask=1.50,
        mid=1.45,
        volume=200,
        open_interest=800,
        iv=0.45,
        iv_unreliable=False,
        finviz_greeks={"delta": -0.18},
        ours_greeks=None,
        greeks_delta=None,
    )
    defaults.update(kwargs)
    return OptionQuote(**defaults)


def _row_from_quote(q: OptionQuote, **extra) -> dict:
    dte = (q.expiry - TODAY).days
    T = dte / 365.0
    delta = extra.pop("delta", None)
    if delta is None:
        delta = GreeksCalculator.delta(100.0, q.strike, T, 0.05, q.iv, "put")
    spread = (q.ask - q.bid) / q.mid if q.mid else 1.0
    row = {
        "ticker": q.ticker,
        "strike": q.strike,
        "dte": dte,
        "bid": q.bid,
        "ask": q.ask,
        "mid": q.mid,
        "delta": delta,
        "iv": q.iv,
        "rv_20d": extra.pop("rv_20d", 0.20),
        "volume": q.volume,
        "open_interest": q.open_interest,
        "quote_age": q.quote_age,
        "last_trade": q.last_trade,
        "earnings_date": extra.pop("earnings_date", None),
        "spot": extra.pop("spot", 100.0),
        "spread": spread,
    }
    row.update(extra)
    return row


def test_hard_filters_drop_earnings_inside_window():
    row = _row_from_quote(_quote(), earnings_date=date(2026, 8, 18))
    kept = hard_filter_rows(pd.DataFrame([row]), today=TODAY)
    assert kept.empty


def test_hard_filters_drop_low_oi_or_volume_wide_spread_stale_and_delta():
    good = _row_from_quote(_quote(), delta=-0.18)
    low_oi = _row_from_quote(_quote(open_interest=400, ticker="LOI"), delta=-0.18)
    low_vol = _row_from_quote(_quote(volume=50, ticker="LVOL"), delta=-0.18)
    wide = _row_from_quote(_quote(bid=1.0, ask=1.40, mid=1.20, ticker="WIDE"), delta=-0.18)
    stale = _row_from_quote(_quote(quote_age=timedelta(minutes=6), ticker="OLD"), delta=-0.18)
    fat_delta = _row_from_quote(_quote(ticker="FAT"), delta=-0.40)
    skinny_delta = _row_from_quote(_quote(ticker="SKIN"), delta=-0.05)
    kept = hard_filter_rows(
        pd.DataFrame([good, low_oi, low_vol, wide, stale, fat_delta, skinny_delta]),
        today=TODAY,
    )
    assert list(kept["ticker"]) == ["TST"]


def test_hard_filter_skips_quote_age_when_max_quote_age_is_none():
    stale = _row_from_quote(_quote(quote_age=timedelta(hours=18), ticker="OLD"), delta=-0.18)
    kept = hard_filter_rows(
        pd.DataFrame([stale]), today=TODAY, max_quote_age=None,
    )
    assert list(kept["ticker"]) == ["OLD"]


def test_rank_is_vrp_then_roc_then_spread_never_raw_premium():
    # High premium, low VRP must lose to low premium, high VRP
    rich = dict(
        ticker="RICH", strike=100.0, dte=7, bid=4.0, ask=4.1, mid=4.05,
        delta=-0.20, iv=0.22, rv_20d=0.20, vrp=0.02,
        annualized_roc=0.50, spread_pct=0.02, capital=10000.0,
        breakeven=95.95, quote_time=NOW, iv_unreliable=False,
    )
    cheap_high_vrp = dict(
        ticker="VRP", strike=100.0, dte=7, bid=0.80, ask=0.84, mid=0.82,
        delta=-0.15, iv=0.40, rv_20d=0.20, vrp=0.20,
        annualized_roc=0.40, spread_pct=0.05, capital=10000.0,
        breakeven=99.18, quote_time=NOW, iv_unreliable=False,
    )
    same_vrp_higher_roc = dict(
        ticker="ROC", strike=100.0, dte=7, bid=0.90, ask=0.94, mid=0.92,
        delta=-0.16, iv=0.40, rv_20d=0.20, vrp=0.20,
        annualized_roc=0.55, spread_pct=0.04, capital=10000.0,
        breakeven=99.08, quote_time=NOW, iv_unreliable=False,
    )
    ranked = rank_rows(pd.DataFrame([rich, cheap_high_vrp, same_vrp_higher_roc]))
    assert list(ranked["ticker"]) == ["ROC", "VRP", "RICH"]


def test_mid_under_10_cents_is_flagged_unreliable_not_dropped():
    q = _quote(bid=0.09, ask=0.10, mid=0.095, iv=0.90, volume=150, open_interest=600)
    row = _row_from_quote(q, delta=-0.12)
    kept = hard_filter_rows(pd.DataFrame([row]), today=TODAY)
    assert len(kept) == 1
    flagged = rank_rows(kept)
    assert bool(flagged.iloc[0]["iv_unreliable"]) is True


def test_table_states_assumptions_and_required_columns():
    df = rank_rows(pd.DataFrame([{
        "ticker": "TST", "strike": 95.0, "dte": 7, "bid": 1.4, "ask": 1.5,
        "mid": 1.45, "delta": -0.18, "iv": 0.45, "rv_20d": 0.25, "vrp": 0.20,
        "annualized_roc": 0.8, "spread_pct": 0.069, "capital": 9500.0,
        "breakeven": 93.55, "quote_time": NOW, "iv_unreliable": False,
    }]))
    text = format_table(df)
    for col in ("ticker", "strike", "DTE", "bid", "ask", "mid", "delta", "IV",
                "20d RV", "VRP", "annualized RoC", "spread", "capital",
                "breakeven", "timestamp"):
        assert col.lower().replace(" ", "") in text.lower().replace(" ", "").replace("%", "")
    assert "r=" in text or "rate" in text.lower()
    assert "export/quote" in text
    assert "Never rank by raw premium" in text


class FakeProvider:
    def __init__(self):
        self.calls: list[str] = []
        self.screener_df = pd.DataFrame({
            "Ticker": ["AAA", "BBB", "CCC", "DDD", "EEE"],
            "Price": [50.0, 100.0, 80.0, 90.0, 10.0],
            "Volatility (Month)": ["1.50%", "5.50%", "5.00%", "4.80%", "1.00%"],
            "Average Volume": [1e6, 3e6, 2e6, 2e6, 9e6],
            "Earnings Date": [None, None, None, "8/19/2026 4:30:00 PM", None],
        })

    def fetch_screener(self, filters: str, **kwargs):
        tickers = kwargs.get("tickers") or []
        self.calls.append(f"screener:{filters}:{','.join(tickers)}")
        return self.screener_df.copy()

    def fetch_history(self, ticker):
        self.calls.append(f"history:{ticker}")
        return _closes()

    def fetch_chain(self, ticker, expiry, **kwargs):
        self.calls.append(f"chain:{ticker}:{expiry}")
        T = 7 / 365.0
        # Strike chosen so abs(put delta) sits in 0.10–0.25 at σ=0.45, S=100
        k = 96.0
        iv = 0.45
        delta = GreeksCalculator.delta(100.0, k, T, 0.05, iv, "put")
        q = _quote(
            ticker=ticker,
            contract=f"{ticker}260821P00096000",
            strike=k,
            iv=iv,
            finviz_greeks={"delta": delta},
        )
        return OptionChain(
            ticker=ticker, expiry=expiry, spot=100.0, spot_method="explicit",
            fetched_at=NOW, quotes=[q], dropped={},
        )

    def dry_run(self, jobs):
        return FetchPlan(n_network_calls=len(jobs), n_cache_hits=0,
                         eta=timedelta(seconds=max(len(jobs) - 1, 0) * 60), jobs=jobs)


def test_run_prints_plan_before_any_fetch(capsys, tmp_path):
    provider = FakeProvider()
    log = []
    orig_screener = provider.fetch_screener
    orig_chain = provider.fetch_chain

    def wrapped_screener(*a, **k):
        printed = capsys.readouterr().out
        log.append(("screener", printed))
        return orig_screener(*a, **k)

    def wrapped_chain(*a, **k):
        printed = capsys.readouterr().out
        log.append(("chain", printed))
        return orig_chain(*a, **k)

    provider.fetch_screener = wrapped_screener
    provider.fetch_chain = wrapped_chain
    PutPremiumScreener(provider, now=lambda: NOW).run(
        filters="fa_div_pos,sec_technology",
        top_n=3,
    )
    assert log[0][0] == "screener"
    assert "Stage 1" in log[0][1]
    assert "ETA" in log[0][1]
    chain_calls = [c for c in provider.calls if c.startswith("chain:")]
    assert len(chain_calls) == 3
    chain_tickers = {c.split(":")[1] for c in chain_calls}
    assert chain_tickers == {"BBB", "CCC", "DDD"}
    hist_calls = [c for c in provider.calls if c.startswith("history:")]
    assert set(hist_calls) == {"history:BBB", "history:CCC", "history:DDD"}

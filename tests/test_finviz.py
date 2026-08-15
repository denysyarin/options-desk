"""Tests for the Finviz Elite adapter.

Network is never hit. HTTP is injected. The options fixture mixes real
export rows (empty Bid / Volume 0, from the 2026-08-21 MSFT dump) with
liquid quotes so hygiene, spot, and Greeks comparison can be asserted.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from xtrading.data.base import FetchJob
from xtrading.data.finviz import (
    FinvizProvider,
    parse_last_trade,
    parse_occ,
)

ET = ZoneInfo("America/New_York")
NOW = datetime(2026, 8, 14, 9, 35, tzinfo=ET)
EXPIRY = date(2026, 8, 21)
FIXTURES = Path(__file__).parent / "fixtures"
OPTIONS_CSV = (FIXTURES / "finviz_options_sample.csv").read_text()
SCREENER_CSV = (FIXTURES / "finviz_screener_sample.csv").read_text()


class FakeClock:
    def __init__(self, t: datetime):
        self.t = t
        self.sleeps: list[float] = []

    def now(self):
        return self.t

    def sleep(self, seconds: float):
        self.sleeps.append(seconds)
        self.t = self.t + timedelta(seconds=seconds)


def _provider(tmp_path, body=OPTIONS_CSV, clock=None, token="test-token"):
    clock = clock or FakeClock(NOW)
    calls: list[str] = []

    def fetcher(url: str) -> str:
        calls.append(url)
        return body

    p = FinvizProvider(
        token=token,
        cache_dir=tmp_path / "cache",
        cache_ttl=timedelta(minutes=15),
        min_interval=timedelta(seconds=60),
        fetcher=fetcher,
        sleep=clock.sleep,
        now=clock.now,
    )
    p._calls = calls  # type: ignore[attr-defined]
    p._clock = clock  # type: ignore[attr-defined]
    return p


# --------------------------------------------------------------------------- #
# OCC / timestamps
# --------------------------------------------------------------------------- #


def test_parse_occ_unpadded_root_and_strike_div_1000():
    parsed = parse_occ("MSFT260821P00495000")
    assert parsed == {
        "ticker": "MSFT",
        "expiry": date(2026, 8, 21),
        "option_type": "put",
        "strike": 495.0,
    }


def test_parse_occ_call_and_fractional_strike():
    parsed = parse_occ("MSFT260821C00492500")
    assert parsed["option_type"] == "call"
    assert parsed["strike"] == 492.5


def test_parse_last_trade_us_eastern():
    ts = parse_last_trade("8/13/2026 3:03:37 PM")
    assert ts == datetime(2026, 8, 13, 15, 3, 37, tzinfo=ET)


def test_parse_last_trade_iso():
    ts = parse_last_trade("2026-08-14T09:32:01")
    assert ts == datetime(2026, 8, 14, 9, 32, 1, tzinfo=ET)


# --------------------------------------------------------------------------- #
# Hygiene, spot, Greeks, staleness
# --------------------------------------------------------------------------- #


def test_drops_empty_bid_and_zero_volume(tmp_path):
    chain = _provider(tmp_path).fetch_chain("MSFT", EXPIRY, max_age=timedelta(hours=24), r=0.0)
    contracts = {q.contract for q in chain.quotes}
    assert "MSFT260821P00215000" not in contracts
    assert "MSFT260821C00215000" not in contracts
    assert chain.dropped["empty_bid"] >= 1
    assert chain.dropped["zero_volume"] >= 1


def test_flags_iv_above_3_instead_of_dropping(tmp_path):
    chain = _provider(tmp_path).fetch_chain("MSFT", EXPIRY, max_age=timedelta(hours=24), r=0.0)
    flagged = [q for q in chain.quotes if q.iv_unreliable]
    assert len(flagged) == 1
    assert flagged[0].strike == 300.0
    assert flagged[0].iv == pytest.approx(13.42)
    # still present, just flagged
    assert flagged[0].contract == "MSFT260821P00300000"


def test_spot_is_median_put_call_parity_of_liquid_pairs(tmp_path):
    # r=0 so S = mid_call - mid_put + K
    # 495: 7.90 - 6.80 + 495 = 496.10
    # 500: 5.50 - 9.40 + 500 = 496.10
    # 300 pair has IV>3 put: excluded from averages
    chain = _provider(tmp_path).fetch_chain("MSFT", EXPIRY, max_age=timedelta(hours=24), r=0.0)
    assert chain.spot == pytest.approx(496.10)
    assert chain.spot_method == "put_call_parity"


def test_explicit_spot_overrides_parity(tmp_path):
    chain = _provider(tmp_path).fetch_chain(
        "MSFT", EXPIRY, spot=500.0, max_age=timedelta(hours=24), r=0.0
    )
    assert chain.spot == 500.0
    assert chain.spot_method == "explicit"


def test_returns_finviz_and_ours_greeks_side_by_side(tmp_path):
    chain = _provider(tmp_path).fetch_chain("MSFT", EXPIRY, max_age=timedelta(hours=24), r=0.0)
    call = next(q for q in chain.quotes if q.contract == "MSFT260821C00495000")
    assert call.finviz_greeks["delta"] == pytest.approx(0.52)
    assert call.ours_greeks is not None
    assert "delta" in call.ours_greeks
    assert "delta" in call.greeks_delta
    assert call.greeks_delta["delta"] == pytest.approx(
        call.ours_greeks["delta"] - call.finviz_greeks["delta"]
    )


def test_stale_quotes_raise_by_default(tmp_path):
    stale_csv = OPTIONS_CSV.replace("8/14/2026 9:32:01 AM", "8/13/2026 3:03:37 PM")
    stale_csv = stale_csv.replace("8/14/2026 9:32:05 AM", "8/13/2026 3:03:37 PM")
    stale_csv = stale_csv.replace("8/14/2026 9:32:10 AM", "8/13/2026 3:03:37 PM")
    stale_csv = stale_csv.replace("8/14/2026 9:32:12 AM", "8/13/2026 3:03:37 PM")
    stale_csv = stale_csv.replace("8/14/2026 9:32:20 AM", "8/13/2026 3:03:37 PM")
    stale_csv = stale_csv.replace("8/14/2026 9:32:21 AM", "8/13/2026 3:03:37 PM")
    p = _provider(tmp_path, body=stale_csv)
    with pytest.raises(ValueError, match="older than"):
        p.fetch_chain("MSFT", EXPIRY)


def test_empty_export_raises(tmp_path):
    header = "Contract Name,Last Trade,Strike,Last Close,Bid,Ask,Change $,Change %,Volume,Open Int.,Type,IV,Delta,Gamma,Theta,Vega,Rho\n"
    p = _provider(tmp_path, body=header)
    with pytest.raises(ValueError, match="no option rows"):
        p.fetch_chain("MSFT", EXPIRY, max_age=timedelta(hours=24))


# --------------------------------------------------------------------------- #
# Token, throttle, cache, dry_run
# --------------------------------------------------------------------------- #


def test_auth_token_never_appears_in_errors(tmp_path):
    secret = "super-secret-token-do-not-leak"

    def fetcher(url: str) -> str:
        raise RuntimeError(f"upstream failed for {url}")

    clock = FakeClock(NOW)
    p = FinvizProvider(
        token=secret,
        cache_dir=tmp_path / "cache",
        fetcher=fetcher,
        sleep=clock.sleep,
        now=clock.now,
    )
    with pytest.raises(RuntimeError) as exc:
        p.fetch_chain("MSFT", EXPIRY, max_age=timedelta(hours=24))
    assert secret not in str(exc.value)
    assert "auth=" not in str(exc.value)


def test_second_fetch_waits_out_the_60s_throttle(tmp_path):
    p = _provider(tmp_path)
    p.fetch_chain("MSFT", EXPIRY, max_age=timedelta(hours=24), r=0.0)
    p.fetch_chain("AAPL", date(2026, 9, 18), max_age=timedelta(hours=24), r=0.0)
    assert p._clock.sleeps  # type: ignore[attr-defined]
    assert p._clock.sleeps[0] == pytest.approx(60.0)


def test_cache_hit_does_not_call_network_or_throttle(tmp_path):
    p = _provider(tmp_path)
    p.fetch_chain("MSFT", EXPIRY, max_age=timedelta(hours=24), r=0.0)
    p.fetch_chain("MSFT", EXPIRY, max_age=timedelta(hours=24), r=0.0)
    assert len(p._calls) == 1  # type: ignore[attr-defined]
    assert p._clock.sleeps == []  # type: ignore[attr-defined]


def test_dry_run_reports_eta_without_fetching(tmp_path):
    p = _provider(tmp_path)
    plan = p.dry_run([
        FetchJob("MSFT", EXPIRY),
        FetchJob("AAPL", date(2026, 9, 18)),
        FetchJob("NVDA", date(2026, 9, 18)),
    ])
    assert plan.n_network_calls == 3
    assert plan.eta == timedelta(seconds=120)  # 0 + 60 + 60
    assert p._calls == []  # type: ignore[attr-defined]


def test_dry_run_counts_warm_cache_as_free(tmp_path):
    p = _provider(tmp_path)
    p.fetch_chain("MSFT", EXPIRY, max_age=timedelta(hours=24), r=0.0)
    plan = p.dry_run([FetchJob("MSFT", EXPIRY), FetchJob("AAPL", date(2026, 9, 18))])
    assert plan.n_network_calls == 1
    assert plan.n_cache_hits == 1
    assert plan.eta == timedelta(0)


def test_token_comes_from_env_when_not_passed(tmp_path, monkeypatch):
    monkeypatch.setenv("FINVIZ_AUTH_TOKEN", "env-token")
    p = _provider(tmp_path, token=None)
    p.fetch_chain("MSFT", EXPIRY, max_age=timedelta(hours=24), r=0.0)
    assert "auth=env-token" in p._calls[0]  # type: ignore[attr-defined]


def test_screener_parses_real_columns(tmp_path):
    p = _provider(tmp_path, body=SCREENER_CSV)
    df = p.fetch_screener(filters="fa_div_pos,sec_technology")
    assert list(df["Ticker"]) == ["AAPL", "MSFT", "NVDA"]
    assert df.loc[df["Ticker"] == "MSFT", "Price"].iloc[0] == pytest.approx(496.39)


def test_screener_custom_columns_go_on_the_url(tmp_path):
    p = _provider(tmp_path, body=SCREENER_CSV)
    p.fetch_screener(filters="sec_technology", view="152", columns="1,65,50,51,63,67,68")
    url = p._calls[0]  # type: ignore[attr-defined]
    assert "v=152" in url
    assert "c=1%2C65%2C50%2C51%2C63%2C67%2C68" in url or "c=1,65,50,51,63,67,68" in url
    assert "auth=test-token" in url


def test_screener_tickers_go_on_url_as_t(tmp_path):
    p = _provider(tmp_path, body=SCREENER_CSV)
    p.fetch_screener(filters="sh_opt_option", tickers=["SPY", "MSFT"])
    url = p._calls[0]  # type: ignore[attr-defined]
    assert "t=SPY%2CMSFT" in url or "t=SPY,MSFT" in url
    assert "f=sh_opt_option" in url


def test_screener_cache_key_includes_tickers(tmp_path):
    p = _provider(tmp_path, body=SCREENER_CSV)
    p.fetch_screener(filters="sh_opt_option", tickers=["AAPL"])
    p.fetch_screener(filters="sh_opt_option", tickers=["MSFT"])
    assert len(p._calls) == 2  # type: ignore[attr-defined]


QUOTE_CSV = (FIXTURES / "finviz_quote_sample.csv").read_text()
OPTIONS_JSON = (FIXTURES / "finviz_options_init.json").read_text()


def test_fetch_history_uses_quote_export_and_returns_closes(tmp_path):
    p = _provider(tmp_path, body=QUOTE_CSV)
    closes = p.fetch_history("MSFT")
    assert "export/quote" in p._calls[0]
    assert "t=MSFT" in p._calls[0]
    assert len(closes) >= 21
    assert closes.iloc[-1] == pytest.approx(110.50)


def test_parse_options_json_has_iv_bids_and_listed_expiries():
    from xtrading.data.finviz import parse_options_payload
    payload = parse_options_payload(OPTIONS_JSON)
    assert payload["currentExpiry"] == "2026-08-21"
    assert "2026-08-21" in payload["expiries"]
    put = next(o for o in payload["options"] if o["type"] == "put")
    assert put["iv"] == pytest.approx(0.22)
    assert put["bidPrice"] == pytest.approx(6.7)


def test_fetch_chain_json_uses_stock_page_not_empty_csv_export(tmp_path):
    html = f'<script id="route-init-data" type="application/json">{OPTIONS_JSON}</script>'
    p = _provider(tmp_path, body=html)
    chain = p.fetch_options_json("MSFT", EXPIRY, max_age=timedelta(hours=24), r=0.0)
    url = p._calls[0]
    assert "/stock?" in url
    assert "export/options" not in url
    assert "ty=oc" in url
    assert "e=2026-08-21" in url
    put = next(q for q in chain.quotes if q.option_type == "put")
    assert put.iv == pytest.approx(0.22)
    assert put.bid == pytest.approx(6.7)
    assert chain.spot == pytest.approx(497.97)


def test_list_expiries_hits_stock_page_without_expiry_param(tmp_path):
    html = f'<script id="route-init-data" type="application/json">{OPTIONS_JSON}</script>'
    p = _provider(tmp_path, body=html)
    dates = p.list_expiries("MSFT")
    assert date(2026, 8, 21) in dates
    assert date(2026, 8, 28) in dates
    assert "e=" not in p._calls[0]


def test_options_json_does_not_consume_export_throttle(tmp_path):
    clock = FakeClock(NOW)
    calls: list[str] = []

    def fetcher(url: str) -> str:
        calls.append(url)
        if "export/quote" in url:
            return QUOTE_CSV
        return f'<script id="route-init-data" type="application/json">{OPTIONS_JSON}</script>'

    p = FinvizProvider(
        token="test-token",
        cache_dir=tmp_path / "cache",
        fetcher=fetcher,
        sleep=clock.sleep,
        now=clock.now,
    )
    p.fetch_history("MSFT")
    p.fetch_options_json("MSFT", EXPIRY, max_age=timedelta(hours=24), r=0.0)
    assert clock.sleeps == []
    assert any("export/quote" in u for u in calls)
    assert any("/stock?" in u for u in calls)


def test_quote_export_waits_after_screener_export(tmp_path):
    clock = FakeClock(NOW)

    def fetcher(url: str) -> str:
        if "export/quote" in url:
            return QUOTE_CSV
        return SCREENER_CSV

    p = FinvizProvider(
        token="test-token",
        cache_dir=tmp_path / "cache",
        fetcher=fetcher,
        sleep=clock.sleep,
        now=clock.now,
    )
    p.fetch_screener("sec_technology")
    p.fetch_history("MSFT")
    assert clock.sleeps == [pytest.approx(60.0)]


def test_dry_run_json_kind_has_no_export_eta(tmp_path):
    p = _provider(tmp_path)
    plan = p.dry_run(
        [FetchJob("MSFT", EXPIRY), FetchJob("AAPL", date(2026, 9, 18))],
        kind="options_json",
    )
    assert plan.n_network_calls == 2
    assert plan.eta == timedelta(0)

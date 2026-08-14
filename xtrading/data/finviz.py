"""Finviz Elite export adapter.

URL shapes (token never hardcoded, never logged):

  options  https://elite.finviz.com/export/options?t={ticker}&ty=oc&e={YYYY-MM-DD}&auth=...
  screener https://elite.finviz.com/export/screener?v=111&f={filters}&auth=...

One export call per 60 seconds, hard-enforced. ``options.py`` is not imported
for HTTP — only for Greeks on already-parsed quotes.
"""
from __future__ import annotations

import os
import re
import time
from io import StringIO
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Optional
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from xtrading.data.base import ChainProvider, FetchJob, FetchPlan, OptionChain, OptionQuote
from xtrading.skills.options import GreeksCalculator

ET = ZoneInfo("America/New_York")
_OCC = re.compile(r"^([A-Z]+)(\d{6})([CP])(\d{8})$")
_LAST_TRADE_FMT = "%m/%d/%Y %I:%M:%S %p"
_OPTIONS_BASE = "https://elite.finviz.com/export/options"
_SCREENER_BASE = "https://elite.finviz.com/export/screener"
_GREEK_COLS = ("delta", "gamma", "theta", "vega", "rho")


def parse_occ(contract: str) -> dict:
    m = _OCC.match(contract.strip().strip('"'))
    if not m:
        raise ValueError(f"not an OCC contract name: {contract!r}")
    root, yymmdd, cp, strike_raw = m.groups()
    yy, mm, dd = int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:6])
    return {
        "ticker": root,
        "expiry": date(2000 + yy, mm, dd),
        "option_type": "call" if cp == "C" else "put",
        "strike": int(strike_raw) / 1000.0,
    }


def parse_last_trade(value: str | None) -> Optional[datetime]:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    return datetime.strptime(text, _LAST_TRADE_FMT).replace(tzinfo=ET)


def _to_float(value) -> Optional[float]:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    text = str(value).strip().replace(",", "").replace("%", "")
    if text == "" or text.lower() == "nan":
        return None
    return float(text)


def _to_int(value) -> int:
    n = _to_float(value)
    return int(n) if n is not None else 0


class FinvizProvider(ChainProvider):
    def __init__(
        self,
        token: Optional[str] = None,
        *,
        cache_dir: Path | str,
        cache_ttl: timedelta = timedelta(minutes=15),
        min_interval: timedelta = timedelta(seconds=60),
        fetcher: Optional[Callable[[str], str]] = None,
        sleep: Callable[[float], None] = time.sleep,
        now: Optional[Callable[[], datetime]] = None,
    ):
        self._token = token if token is not None else os.environ.get("FINVIZ_AUTH_TOKEN")
        self.cache_dir = Path(cache_dir)
        self.cache_ttl = cache_ttl
        self.min_interval = min_interval
        self._fetcher = fetcher or self._default_fetch
        self._sleep = sleep
        self._now = now or (lambda: datetime.now(tz=ET))
        self._last_network_at: Optional[datetime] = None
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # Public
    # ------------------------------------------------------------------ #

    def fetch_chain(
        self,
        ticker: str,
        expiry: date,
        *,
        spot: Optional[float] = None,
        max_age: timedelta = timedelta(minutes=5),
        r: float = 0.05,
    ) -> OptionChain:
        ticker = ticker.upper()
        body = self._load_or_fetch("options", ticker, expiry, extra={"ty": "oc", "e": expiry.isoformat(), "t": ticker})
        return self._parse_chain(body, ticker, expiry, spot=spot, max_age=max_age, r=r)

    def fetch_screener(self, filters: str, *, view: str = "111") -> pd.DataFrame:
        body = self._load_or_fetch(
            "screener",
            filters.replace(",", "_"),
            None,
            extra={"v": view, "f": filters},
        )
        return pd.read_csv(StringIO(body))

    def dry_run(self, jobs: list[FetchJob]) -> FetchPlan:
        n_hits = 0
        n_net = 0
        for job in jobs:
            if self._cache_path("options", job.ticker.upper(), job.expiry).exists() and self._cache_fresh(
                self._cache_path("options", job.ticker.upper(), job.expiry)
            ):
                n_hits += 1
            else:
                n_net += 1
        wait_steps = max(n_net - 1, 0)
        return FetchPlan(
            n_network_calls=n_net,
            n_cache_hits=n_hits,
            eta=timedelta(seconds=wait_steps * self.min_interval.total_seconds()),
            jobs=list(jobs),
        )

    # ------------------------------------------------------------------ #
    # HTTP / cache / throttle
    # ------------------------------------------------------------------ #

    def _token_or_raise(self) -> str:
        if not self._token:
            raise ValueError("FINVIZ_AUTH_TOKEN is missing")
        return self._token

    def _redact(self, text: str) -> str:
        token = self._token or ""
        text = re.sub(r"([?&])auth=[^&\s]+", r"\1auth=REDACTED", text)
        if token:
            text = text.replace(token, "REDACTED")
        # Drop the query field entirely so logs never even say "auth="
        text = re.sub(r"\?auth=REDACTED(&)?", lambda m: "?" if m.group(1) else "", text)
        text = re.sub(r"&auth=REDACTED", "", text)
        return text

    def _options_url(self, ticker: str, expiry: date) -> str:
        q = urlencode({"t": ticker, "ty": "oc", "e": expiry.isoformat(), "auth": self._token_or_raise()})
        return f"{_OPTIONS_BASE}?{q}"

    def _screener_url(self, filters: str, view: str) -> str:
        q = urlencode({"v": view, "f": filters, "auth": self._token_or_raise()})
        return f"{_SCREENER_BASE}?{q}"

    def _cache_path(self, kind: str, key: str, expiry: Optional[date]) -> Path:
        day = self._now().astimezone(ET).date().isoformat()
        exp = expiry.isoformat() if expiry else "none"
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", f"{kind}_{key}_{exp}_{day}")
        return self.cache_dir / f"{safe}.csv"

    def _stamp_path(self, csv_path: Path) -> Path:
        return csv_path.with_suffix(".fetched_at")

    def _cache_fresh(self, csv_path: Path) -> bool:
        stamp = self._stamp_path(csv_path)
        if not csv_path.exists() or not stamp.exists():
            return False
        fetched = datetime.fromisoformat(stamp.read_text().strip())
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=ET)
        return (self._now() - fetched) <= self.cache_ttl

    def _throttle(self) -> None:
        if self._last_network_at is None:
            return
        elapsed = self._now() - self._last_network_at
        wait = self.min_interval - elapsed
        seconds = wait.total_seconds()
        if seconds > 0:
            print(f"Finviz throttle: waiting {seconds:.0f}s before next export call")
            self._sleep(seconds)

    def _default_fetch(self, url: str) -> str:
        req = Request(url, headers={"User-Agent": "options-desk/0.1"})
        try:
            with urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8")
        except URLError as exc:
            raise RuntimeError(self._redact(f"Finviz request failed: {exc}")) from None

    def _load_or_fetch(self, kind: str, key: str, expiry: Optional[date], extra: dict) -> str:
        path = self._cache_path(kind, key, expiry)
        if self._cache_fresh(path):
            return path.read_text()
        if kind == "options":
            url = self._options_url(extra["t"], date.fromisoformat(extra["e"]))
        else:
            url = self._screener_url(extra["f"], extra["v"])
        self._throttle()
        try:
            body = self._fetcher(url)
        except Exception as exc:
            raise type(exc)(self._redact(str(exc))) from None
        self._last_network_at = self._now()
        path.write_text(body)
        self._stamp_path(path).write_text(self._now().isoformat())
        return body

    # ------------------------------------------------------------------ #
    # Parse
    # ------------------------------------------------------------------ #

    def _parse_chain(
        self,
        body: str,
        ticker: str,
        expiry: date,
        *,
        spot: Optional[float],
        max_age: timedelta,
        r: float,
    ) -> OptionChain:
        df = pd.read_csv(StringIO(body))
        if df.empty:
            raise ValueError("no option rows")
        now = self._now()
        T = max((expiry - now.astimezone(ET).date()).days, 0) / 365.0
        quotes: list[OptionQuote] = []
        n_empty_bid = 0
        n_zero_vol = 0
        for _, row in df.iterrows():
            contract = str(row["Contract Name"]).strip().strip('"')
            occ = parse_occ(contract)
            bid = _to_float(row.get("Bid"))
            volume = _to_int(row.get("Volume"))
            if bid is None:
                n_empty_bid += 1
            if volume == 0:
                n_zero_vol += 1
            if bid is None or volume == 0:
                continue
            ask = _to_float(row.get("Ask"))
            mid = (bid + ask) / 2.0 if ask is not None else None
            iv = _to_float(row.get("IV"))
            iv_unreliable = iv is not None and iv > 3.0
            last_trade = parse_last_trade(row.get("Last Trade"))
            quote_age = (now - last_trade) if last_trade is not None else None
            finviz_greeks = {
                "delta": _to_float(row.get("Delta")),
                "gamma": _to_float(row.get("Gamma")),
                "theta": _to_float(row.get("Theta")),
                "vega": _to_float(row.get("Vega")),
                "rho": _to_float(row.get("Rho")),
            }
            quotes.append(OptionQuote(
                contract=contract,
                ticker=occ["ticker"],
                expiry=occ["expiry"],
                option_type=occ["option_type"],
                strike=occ["strike"],
                last_trade=last_trade,
                quote_age=quote_age,
                last_close=_to_float(row.get("Last Close")),
                bid=bid,
                ask=ask,
                mid=mid,
                volume=volume,
                open_interest=_to_int(row.get("Open Int.")),
                iv=iv,
                iv_unreliable=iv_unreliable,
                finviz_greeks=finviz_greeks,
                ours_greeks=None,
                greeks_delta=None,
            ))

        dropped = {"empty_bid": n_empty_bid, "zero_volume": n_zero_vol}
        if not quotes:
            raise ValueError("no option rows remaining after hygiene")

        if spot is not None:
            resolved_spot = float(spot)
            spot_method = "explicit"
        else:
            resolved_spot = self._parity_spot(quotes, T=T, r=r)
            spot_method = "put_call_parity"

        if T > 0:
            for q in quotes:
                if q.iv is None:
                    continue
                ours = GreeksCalculator.all_greeks(
                    resolved_spot, q.strike, T, r, q.iv, q.option_type
                )
                q.ours_greeks = ours
                q.greeks_delta = {
                    k: ours[k] - q.finviz_greeks[k]
                    for k in _GREEK_COLS
                    if q.finviz_greeks.get(k) is not None
                }

        stale = [
            q for q in quotes
            if q.quote_age is None or q.quote_age > max_age
        ]
        if stale:
            age = max((q.quote_age or max_age) for q in stale)
            raise ValueError(
                f"quotes older than max_age={max_age}: oldest age {age}"
            )

        return OptionChain(
            ticker=ticker,
            expiry=expiry,
            spot=resolved_spot,
            spot_method=spot_method,
            fetched_at=now,
            quotes=quotes,
            dropped=dropped,
        )

    @staticmethod
    def _parity_spot(quotes: list[OptionQuote], *, T: float, r: float) -> float:
        by_strike: dict[float, dict[str, OptionQuote]] = {}
        for q in quotes:
            if q.iv_unreliable or q.mid is None:
                continue
            by_strike.setdefault(q.strike, {})[q.option_type] = q
        implied = []
        disc = np.exp(-r * T) if T > 0 else 1.0
        for strike, sides in by_strike.items():
            if "call" in sides and "put" in sides:
                implied.append(sides["call"].mid - sides["put"].mid + strike * disc)
        if not implied:
            raise ValueError("cannot derive spot: no liquid put/call pairs")
        return float(np.median(implied))

"""Vendor-agnostic option-chain types.

A different data vendor drops in by implementing ``ChainProvider``.
``options.py`` stays pure math and never imports this package.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional


@dataclass(frozen=True)
class FetchJob:
    ticker: str
    expiry: date


@dataclass
class FetchPlan:
    n_network_calls: int
    n_cache_hits: int
    eta: timedelta
    jobs: list[FetchJob] = field(default_factory=list)


@dataclass
class OptionQuote:
    contract: str
    ticker: str
    expiry: date
    option_type: str
    strike: float
    last_trade: Optional[datetime]
    quote_age: Optional[timedelta]
    last_close: Optional[float]
    bid: Optional[float]
    ask: Optional[float]
    mid: Optional[float]
    volume: int
    open_interest: int
    iv: Optional[float]
    iv_unreliable: bool
    finviz_greeks: dict
    ours_greeks: Optional[dict]
    greeks_delta: Optional[dict]


@dataclass
class OptionChain:
    ticker: str
    expiry: date
    spot: float
    spot_method: str
    fetched_at: datetime
    quotes: list[OptionQuote]
    dropped: dict


class ChainProvider(ABC):
    @abstractmethod
    def fetch_chain(
        self,
        ticker: str,
        expiry: date,
        *,
        spot: Optional[float] = None,
        max_age: timedelta = timedelta(minutes=5),
        r: float = 0.05,
        enforce_stale: bool = True,
    ) -> OptionChain:
        raise NotImplementedError

    @abstractmethod
    def dry_run(self, jobs: list[FetchJob]) -> FetchPlan:
        raise NotImplementedError

"""
xtrading.skills.options
========================

Options pricing, Greeks, multi-leg strategy analysis, volatility-surface
analytics, and option-chain screening.

Every closed-form Greek in this module is defined so that it matches (to a
central-finite-difference tolerance) the corresponding partial derivative of
``OptionsPricing.black_scholes``. That equivalence is what's actually tested
in ``tests/test_options.py`` — the worked examples that used to live in
``.claude/skills/options-trading/SKILL.md`` were hand-typed and wrong; they
are not, and must never become, a source of truth for this module.

Scaling conventions (documented explicitly because the finance literature is
inconsistent about them — pick a convention, then be consistent):

  * delta   -- raw, dV/dS, in [-1, 1] (put) or [0, 1] (call)
  * gamma   -- raw, d^2V/dS^2
  * theta   -- per calendar day: annual dV/dt / 365   (dV/dt = -dV/dT)
  * vega    -- per 1 percentage point of IV: annual dV/dsigma / 100
  * rho     -- per 1 percentage point of the risk-free rate: annual dV/dr / 100
  * charm   -- per calendar day: d(delta)/dt / 365 (== -d(delta)/dT / 365)
  * vanna   -- per 1 percentage point of IV: d(delta)/dsigma / 100
  * volga   -- per 1 percentage point of IV: d(vega)/dsigma, where vega is the
               already-scaled (per-1%-point) vega above, i.e. raw vomma / 100

All five first-order Greeks and all three second-order Greeks (charm, vanna,
volga) are identical for calls and puts *except* delta/gamma/theta/rho, which
differ by the usual put-call terms. Charm and vanna are literally identical
between calls and puts because delta_put = delta_call - 1 (a constant
offset with zero derivative in T or sigma) -- see
``test_put_call_charm_and_vanna_are_equal``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.stats import norm

_VALID_TYPES = ("call", "put")


def _check_type(option_type: str) -> None:
    if option_type not in _VALID_TYPES:
        raise ValueError(f"option_type must be 'call' or 'put', got {option_type!r}")


def _d1_d2(S: float, K: float, T: float, r: float, sigma: float):
    if sigma <= 0:
        raise ValueError("sigma must be > 0")
    if T <= 0:
        raise ValueError("T must be > 0 (callers handle the T<=0 boundary themselves)")
    if S <= 0 or K <= 0:
        raise ValueError("S and K must be > 0")
    sqrt_t = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    return d1, d2


def _prob_above(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Risk-neutral P(S_T > K), using the standard textbook N(d2) convention."""
    _, d2 = _d1_d2(S, K, T, r, sigma)
    return float(norm.cdf(d2))


def _prob_below(S: float, K: float, T: float, r: float, sigma: float) -> float:
    return 1.0 - _prob_above(S, K, T, r, sigma)


# --------------------------------------------------------------------------- #
# 1. Pricing
# --------------------------------------------------------------------------- #


class OptionsPricing:
    """Black-Scholes-Merton (1973) pricing, IV extraction, binomial and Monte Carlo pricers."""

    @staticmethod
    def black_scholes(S: float, K: float, T: float, r: float, sigma: float,
                       option_type: str = "call") -> float:
        _check_type(option_type)
        if T <= 0:
            intrinsic = max(S - K, 0.0) if option_type == "call" else max(K - S, 0.0)
            return float(intrinsic)
        d1, d2 = _d1_d2(S, K, T, r, sigma)
        if option_type == "call":
            return float(S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2))
        return float(K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1))

    @staticmethod
    def implied_volatility(market_price: float, S: float, K: float, T: float, r: float,
                            option_type: str = "call", lo: float = 1e-6, hi: float = 8.0,
                            xtol: float = 1e-12) -> float:
        _check_type(option_type)
        # European no-arbitrage floor uses the *discounted* strike, not raw
        # intrinsic (K-S) -- a European put can legitimately price below K-S
        # when the present value of K is meaningfully less than K itself.
        disc_k = K * math.exp(-r * T)
        floor = max(S - disc_k, 0.0) if option_type == "call" else max(disc_k - S, 0.0)
        if market_price < floor - 1e-9:
            raise ValueError("market_price is below the no-arbitrage floor; no valid IV exists")

        def f(sigma: float) -> float:
            return OptionsPricing.black_scholes(S, K, T, r, sigma, option_type) - market_price

        f_lo, f_hi = f(lo), f(hi)
        if f_lo > 0 or f_hi < 0:
            raise ValueError(f"market_price={market_price} not bracketed by sigma in [{lo}, {hi}]")
        return float(brentq(f, lo, hi, xtol=xtol))

    @staticmethod
    def binomial_price(S: float, K: float, T: float, r: float, sigma: float,
                        option_type: str = "call", american: bool = False,
                        n_steps: int = 400) -> float:
        _check_type(option_type)
        if T <= 0:
            return OptionsPricing.black_scholes(S, K, T, r, sigma, option_type)
        dt = T / n_steps
        u = math.exp(sigma * math.sqrt(dt))
        d = 1.0 / u
        disc = math.exp(-r * dt)
        p = (math.exp(r * dt) - d) / (u - d)
        if not (0.0 < p < 1.0):
            raise ValueError("binomial parameters imply p outside (0, 1); reduce dt or check inputs")

        j = np.arange(n_steps + 1)
        st = S * u ** (n_steps - j) * d ** j
        values = np.maximum(st - K, 0.0) if option_type == "call" else np.maximum(K - st, 0.0)

        for i in range(n_steps - 1, -1, -1):
            values = disc * (p * values[:-1] + (1 - p) * values[1:])
            if american:
                j = np.arange(i + 1)
                st_i = S * u ** (i - j) * d ** j
                exercise = np.maximum(st_i - K, 0.0) if option_type == "call" else np.maximum(K - st_i, 0.0)
                values = np.maximum(values, exercise)
        return float(values[0])

    @staticmethod
    def monte_carlo_price(S: float, K: float, T: float, r: float, sigma: float,
                           option_type: str = "call", n_paths: int = 100_000,
                           seed: Optional[int] = None) -> dict:
        _check_type(option_type)
        if T <= 0:
            price = OptionsPricing.black_scholes(S, K, T, r, sigma, option_type)
            return {"price": price, "std_error": 0.0, "ci_95_lower": price, "ci_95_upper": price}
        rng = np.random.default_rng(seed)
        z = rng.standard_normal(n_paths)
        st = S * np.exp((r - 0.5 * sigma ** 2) * T + sigma * math.sqrt(T) * z)
        payoff = np.maximum(st - K, 0.0) if option_type == "call" else np.maximum(K - st, 0.0)
        disc_payoff = math.exp(-r * T) * payoff
        price = float(disc_payoff.mean())
        se = float(disc_payoff.std(ddof=1) / math.sqrt(n_paths))
        return {
            "price": price, "std_error": se,
            "ci_95_lower": price - 1.96 * se, "ci_95_upper": price + 1.96 * se,
        }


# --------------------------------------------------------------------------- #
# 2. Greeks
# --------------------------------------------------------------------------- #


class GreeksCalculator:
    """First- and second-order Greeks. See module docstring for scaling conventions."""

    @staticmethod
    def delta(S: float, K: float, T: float, r: float, sigma: float, option_type: str = "call") -> float:
        _check_type(option_type)
        if T <= 0:
            if option_type == "call":
                return 1.0 if S > K else (0.0 if S < K else 0.5)
            return -1.0 if S < K else (0.0 if S > K else -0.5)
        d1, _ = _d1_d2(S, K, T, r, sigma)
        return float(norm.cdf(d1) if option_type == "call" else norm.cdf(d1) - 1.0)

    @staticmethod
    def gamma(S: float, K: float, T: float, r: float, sigma: float, option_type: str = "call") -> float:
        _check_type(option_type)
        if T <= 0:
            return 0.0
        d1, _ = _d1_d2(S, K, T, r, sigma)
        return float(norm.pdf(d1) / (S * sigma * math.sqrt(T)))

    @staticmethod
    def vega(S: float, K: float, T: float, r: float, sigma: float, option_type: str = "call") -> float:
        _check_type(option_type)
        if T <= 0:
            return 0.0
        d1, _ = _d1_d2(S, K, T, r, sigma)
        return float(S * norm.pdf(d1) * math.sqrt(T) / 100.0)

    @staticmethod
    def theta(S: float, K: float, T: float, r: float, sigma: float, option_type: str = "call") -> float:
        _check_type(option_type)
        if T <= 0:
            return 0.0
        d1, d2 = _d1_d2(S, K, T, r, sigma)
        term1 = -S * norm.pdf(d1) * sigma / (2 * math.sqrt(T))
        if option_type == "call":
            term2 = -r * K * math.exp(-r * T) * norm.cdf(d2)
        else:
            term2 = r * K * math.exp(-r * T) * norm.cdf(-d2)
        return float((term1 + term2) / 365.0)

    @staticmethod
    def rho(S: float, K: float, T: float, r: float, sigma: float, option_type: str = "call") -> float:
        _check_type(option_type)
        if T <= 0:
            return 0.0
        _, d2 = _d1_d2(S, K, T, r, sigma)
        if option_type == "call":
            return float(K * T * math.exp(-r * T) * norm.cdf(d2) / 100.0)
        return float(-K * T * math.exp(-r * T) * norm.cdf(-d2) / 100.0)

    @staticmethod
    def charm(S: float, K: float, T: float, r: float, sigma: float, option_type: str = "call") -> float:
        # Same closed form for calls and puts -- see module docstring.
        _check_type(option_type)
        if T <= 0:
            return 0.0
        d1, d2 = _d1_d2(S, K, T, r, sigma)
        sqrt_t = math.sqrt(T)
        raw = -norm.pdf(d1) * (2 * r * T - d2 * sigma * sqrt_t) / (2 * T * sigma * sqrt_t)
        return float(raw / 365.0)

    @staticmethod
    def vanna(S: float, K: float, T: float, r: float, sigma: float, option_type: str = "call") -> float:
        # Same closed form for calls and puts -- see module docstring.
        _check_type(option_type)
        if T <= 0:
            return 0.0
        d1, d2 = _d1_d2(S, K, T, r, sigma)
        raw = -norm.pdf(d1) * d2 / sigma
        return float(raw / 100.0)

    @staticmethod
    def volga(S: float, K: float, T: float, r: float, sigma: float, option_type: str = "call") -> float:
        _check_type(option_type)
        if T <= 0:
            return 0.0
        d1, d2 = _d1_d2(S, K, T, r, sigma)
        vega_scaled = GreeksCalculator.vega(S, K, T, r, sigma, option_type)
        return float(vega_scaled * d1 * d2 / sigma)

    @staticmethod
    def all_greeks(S: float, K: float, T: float, r: float, sigma: float, option_type: str = "call") -> dict:
        _check_type(option_type)
        price = OptionsPricing.black_scholes(S, K, T, r, sigma, option_type)
        intrinsic = max(S - K, 0.0) if option_type == "call" else max(K - S, 0.0)
        moneyness_ratio = S / K
        if abs(moneyness_ratio - 1.0) < 0.01:
            moneyness = "ATM"
        elif (option_type == "call" and S > K) or (option_type == "put" and S < K):
            moneyness = "ITM"
        else:
            moneyness = "OTM"
        return {
            "price": price,
            "delta": GreeksCalculator.delta(S, K, T, r, sigma, option_type),
            "gamma": GreeksCalculator.gamma(S, K, T, r, sigma, option_type),
            "theta": GreeksCalculator.theta(S, K, T, r, sigma, option_type),
            "vega": GreeksCalculator.vega(S, K, T, r, sigma, option_type),
            "rho": GreeksCalculator.rho(S, K, T, r, sigma, option_type),
            "charm": GreeksCalculator.charm(S, K, T, r, sigma, option_type),
            "vanna": GreeksCalculator.vanna(S, K, T, r, sigma, option_type),
            "volga": GreeksCalculator.volga(S, K, T, r, sigma, option_type),
            "moneyness": moneyness,
            "intrinsic": float(intrinsic),
            "time_value": float(price - intrinsic),
        }


# --------------------------------------------------------------------------- #
# 3. Strategy Builder
# --------------------------------------------------------------------------- #


@dataclass
class StrategyResult:
    strategy_name: str
    net_premium: float
    max_profit: float
    max_loss: float
    breakeven_prices: list
    risk_reward: float
    probability_of_profit: float


@dataclass
class _Strategy:
    strategy_name: str
    symbol: str
    S: float
    T: float
    r: float
    sigma: float
    _analyse_fn: object = field(repr=False)

    def analyse(self) -> StrategyResult:
        return self._analyse_fn()


class StrategyBuilder:
    """Multi-leg payoff analysis at expiration, priced off Black-Scholes premia today.

    ``probability_of_profit`` uses the same risk-neutral N(d2) convention as
    ``OptionsPricing`` -- it is the standard textbook approximation, not a
    physical-measure probability.
    """

    @staticmethod
    def bull_call_spread(symbol: str, S: float, K_long: float, K_short: float,
                          T: float, r: float, sigma: float) -> _Strategy:
        if not K_long < K_short:
            raise ValueError("K_long must be < K_short")
        price_long = OptionsPricing.black_scholes(S, K_long, T, r, sigma, "call")
        price_short = OptionsPricing.black_scholes(S, K_short, T, r, sigma, "call")
        net_premium = price_short - price_long  # negative => net debit paid
        width = K_short - K_long
        max_profit = width + net_premium
        max_loss = net_premium
        breakeven = K_long - net_premium

        def _analyse() -> StrategyResult:
            pop = _prob_above(S, breakeven, T, r, sigma)
            rr = max_profit / abs(max_loss) if max_loss != 0 else float("inf")
            return StrategyResult("Bull Call Spread", net_premium, max_profit, max_loss,
                                   [round(breakeven, 4)], rr, pop)

        return _Strategy("Bull Call Spread", symbol, S, T, r, sigma, _analyse)

    @staticmethod
    def iron_condor(symbol: str, S: float, K_put_long: float, K_put_short: float,
                     K_call_short: float, K_call_long: float, T: float, r: float,
                     sigma: float) -> _Strategy:
        if not (K_put_long < K_put_short < K_call_short < K_call_long):
            raise ValueError("strikes must satisfy K_put_long < K_put_short < K_call_short < K_call_long")
        p_pl = OptionsPricing.black_scholes(S, K_put_long, T, r, sigma, "put")
        p_ps = OptionsPricing.black_scholes(S, K_put_short, T, r, sigma, "put")
        p_cs = OptionsPricing.black_scholes(S, K_call_short, T, r, sigma, "call")
        p_cl = OptionsPricing.black_scholes(S, K_call_long, T, r, sigma, "call")
        net_premium = (p_ps - p_pl) + (p_cs - p_cl)  # positive => net credit received
        put_wing = K_put_short - K_put_long
        call_wing = K_call_long - K_call_short
        max_profit = net_premium
        max_loss = -(max(put_wing, call_wing) - net_premium)
        be_low = K_put_short - net_premium
        be_high = K_call_short + net_premium

        def _analyse() -> StrategyResult:
            pop = _prob_above(S, be_low, T, r, sigma) - _prob_above(S, be_high, T, r, sigma)
            rr = max_profit / abs(max_loss) if max_loss != 0 else float("inf")
            return StrategyResult("Iron Condor", net_premium, max_profit, max_loss,
                                   [round(be_low, 4), round(be_high, 4)], rr, pop)

        return _Strategy("Iron Condor", symbol, S, T, r, sigma, _analyse)

    @staticmethod
    def long_straddle(symbol: str, S: float, K: float, T: float, r: float, sigma: float) -> _Strategy:
        price_call = OptionsPricing.black_scholes(S, K, T, r, sigma, "call")
        price_put = OptionsPricing.black_scholes(S, K, T, r, sigma, "put")
        net_premium = -(price_call + price_put)  # debit paid
        debit = -net_premium
        be_low = K - debit
        be_high = K + debit
        max_profit = float("inf")  # unbounded via the call leg
        max_loss = net_premium

        def _analyse() -> StrategyResult:
            pop = _prob_below(S, be_low, T, r, sigma) + _prob_above(S, be_high, T, r, sigma)
            return StrategyResult("Long Straddle", net_premium, max_profit, max_loss,
                                   [round(be_low, 4), round(be_high, 4)], float("inf"), pop)

        return _Strategy("Long Straddle", symbol, S, T, r, sigma, _analyse)


# --------------------------------------------------------------------------- #
# 4. Volatility Surface
# --------------------------------------------------------------------------- #


class VolatilitySurface:
    """Wraps a long-format IV surface: columns ``strike``, ``expiry_days``, ``iv``.

    ``S`` (underlying price) is optional and currently only accepted for API
    forward-compatibility -- ``smile_at_expiry`` uses a fixed +/-10%
    strike-offset proxy for the wings rather than true 25-delta strikes,
    because true delta-matched strikes need per-row deltas the input schema
    doesn't carry. This is called out in the returned dict's ``note`` field.
    """

    def __init__(self, surface_data: pd.DataFrame, S: Optional[float] = None, r: float = 0.0):
        required = {"strike", "expiry_days", "iv"}
        missing = required - set(surface_data.columns)
        if missing:
            raise ValueError(f"surface_data missing columns: {sorted(missing)}")
        self.data = surface_data.copy()
        self.S = S
        self.r = r

    def _slice(self, expiry_days) -> pd.DataFrame:
        rows = self.data[self.data["expiry_days"] == expiry_days].sort_values("strike")
        if rows.empty:
            raise ValueError(f"no rows for expiry_days={expiry_days}")
        return rows

    def smile_at_expiry(self, expiry_days, atm_strike: float) -> dict:
        rows = self._slice(expiry_days)
        strikes, ivs = rows["strike"].to_numpy(dtype=float), rows["iv"].to_numpy(dtype=float)
        atm_iv = float(np.interp(atm_strike, strikes, ivs))
        put_wing_iv = float(np.interp(atm_strike * 0.9, strikes, ivs))
        call_wing_iv = float(np.interp(atm_strike * 1.1, strikes, ivs))
        skew_25d = round(call_wing_iv - put_wing_iv, 4)
        butterfly_25d = round((put_wing_iv + call_wing_iv) / 2 - atm_iv, 4)
        bias = "put_skew" if skew_25d < 0 else ("call_skew" if skew_25d > 0 else "flat")
        return {
            "atm_iv": round(atm_iv, 4), "skew_25d": skew_25d,
            "butterfly_25d": butterfly_25d, "bias": bias,
            "note": "wings are a +/-10% strike-offset proxy, not true 25-delta strikes",
        }

    def term_structure(self, atm_strike: float) -> pd.DataFrame:
        rows = []
        for expiry_days, grp in self.data.groupby("expiry_days"):
            grp = grp.sort_values("strike")
            atm_iv = float(np.interp(atm_strike, grp["strike"], grp["iv"]))
            t_years = expiry_days / 365.0
            # ATM straddle ~= 0.8 * S * sigma * sqrt(T) (Brenner-Subrahmanyam),
            # expressed here as a %-of-spot cost, then annualised.
            cost_pct = 0.8 * atm_iv * math.sqrt(t_years) * 100.0
            annualised_cost_pct = cost_pct * (365.0 / expiry_days)
            rows.append({
                "expiry_days": expiry_days, "atm_iv": round(atm_iv, 4),
                "vix_equiv": round(atm_iv * 100, 2),
                "annualised_cost_pct": round(annualised_cost_pct, 2),
            })
        return pd.DataFrame(rows).sort_values("expiry_days").reset_index(drop=True)

    @staticmethod
    def iv_rank(current_iv: float, historical_ivs: pd.Series) -> dict:
        hist = pd.Series(historical_ivs).dropna()
        if hist.empty:
            raise ValueError("historical_ivs is empty")
        rank = float((hist < current_iv).mean() * 100)
        regime = "HIGH_IV" if rank > 70 else ("LOW_IV" if rank < 30 else "NORMAL_IV")
        bias = {"HIGH_IV": "SHORT_PREMIUM", "LOW_IV": "LONG_PREMIUM", "NORMAL_IV": "NEUTRAL"}[regime]
        return {"iv_rank": round(rank, 1), "regime": regime, "strategy_bias": bias}

    def validate_no_arbitrage(self) -> dict:
        """Calendar-spread check only.

        For each strike present at more than one expiry, total implied
        variance (iv^2 * T) must be non-decreasing in T. This does NOT check
        strike-dimension (butterfly/vertical) arbitrage -- that requires
        converting IV to price, which needs the underlying price and is out
        of scope for an IV-only surface. Documented limitation, not a
        full arbitrage-free proof.
        """
        violations = []
        for strike, grp in self.data.groupby("strike"):
            grp = grp.sort_values("expiry_days")
            days = grp["expiry_days"].to_numpy()
            total_var = (grp["iv"].to_numpy() ** 2) * (days / 365.0)
            for i in range(1, len(total_var)):
                if total_var[i] < total_var[i - 1] - 1e-12:
                    violations.append({
                        "strike": float(strike),
                        "expiry_days_short": int(days[i - 1]), "expiry_days_long": int(days[i]),
                        "total_variance_short": float(total_var[i - 1]),
                        "total_variance_long": float(total_var[i]),
                    })
        return {"arbitrage_free": len(violations) == 0, "violations": violations, "n_violations": len(violations)}


# --------------------------------------------------------------------------- #
# 5. Option Screener
# --------------------------------------------------------------------------- #


class OptionScreener:
    """Screens a long-format chain: columns ``strike``, ``expiry_days``, ``iv``.

    Theoretical price/delta/probability-of-profit are computed from those
    three columns plus the underlying price and rate given at construction --
    this screener does not require a chain that already carries broker
    Greeks. ``probability_of_profit`` assumes a short-premium setup (the
    screener's stated purpose): it is P(the option expires OTM).
    """

    def __init__(self, chain_df: pd.DataFrame, underlying_price: float, r: float = 0.05):
        required = {"strike", "expiry_days", "iv"}
        missing = required - set(chain_df.columns)
        if missing:
            raise ValueError(f"chain_df missing columns: {sorted(missing)}")
        self.chain = chain_df.copy()
        self.S = underlying_price
        self.r = r

    def screen(self, min_pop: float = 0.0, min_dte: int = 0, max_dte: int = 10_000,
               min_delta: float = 0.0, max_delta: float = 1.0, option_type: str = "put") -> pd.DataFrame:
        _check_type(option_type)
        rows = self.chain[(self.chain["expiry_days"] >= min_dte) & (self.chain["expiry_days"] <= max_dte)]
        out = []
        for _, row in rows.iterrows():
            t_years = row["expiry_days"] / 365.0
            if t_years <= 0:
                continue
            delta = GreeksCalculator.delta(self.S, row["strike"], t_years, self.r, row["iv"], option_type)
            if not (min_delta <= abs(delta) <= max_delta):
                continue
            pop = (_prob_below(self.S, row["strike"], t_years, self.r, row["iv"]) if option_type == "call"
                   else _prob_above(self.S, row["strike"], t_years, self.r, row["iv"]))
            if pop < min_pop:
                continue
            price = OptionsPricing.black_scholes(self.S, row["strike"], t_years, self.r, row["iv"], option_type)
            out.append({
                "strike": float(row["strike"]), "expiry_days": int(row["expiry_days"]),
                "iv": float(row["iv"]), "delta": delta, "price": price, "probability_of_profit": pop,
            })
        return pd.DataFrame(out)

    def expected_move(self, expiry_days) -> dict:
        rows = self.chain[self.chain["expiry_days"] == expiry_days].sort_values("strike")
        if rows.empty:
            raise ValueError(f"no rows for expiry_days={expiry_days}")
        atm_iv = float(np.interp(self.S, rows["strike"], rows["iv"]))
        t_years = expiry_days / 365.0
        move_pts = self.S * atm_iv * math.sqrt(t_years)
        move_pct = move_pts / self.S * 100
        return {
            "expected_move_pts": round(move_pts, 4), "expected_move_pct": round(move_pct, 4),
            "upper_bound": round(self.S + move_pts, 4), "lower_bound": round(self.S - move_pts, 4),
        }

"""
Tests for xtrading.skills.options.

Ground truth here is derived analytically/numerically in this file -- NEVER
from options-trading/SKILL.md's worked examples. Those were found to be
fabricated (hand-typed "-> ..." comments that didn't match the file's own
formulas) and must not be trusted as expected values in a test.

Every first-order Greek is checked against a central finite difference of
OptionsPricing.black_scholes. Every second-order Greek (charm, vanna, volga)
is checked against a mixed/second finite difference of black_scholes
directly -- not against another Greek's implementation -- so nothing here is
circular.
"""
import math

import numpy as np
import pandas as pd
import pytest

from xtrading.skills.options import (
    GreeksCalculator,
    OptionScreener,
    OptionsPricing,
    StrategyBuilder,
    VolatilitySurface,
)


# --------------------------------------------------------------------------- #
# Pricing
# --------------------------------------------------------------------------- #


def test_put_call_parity():
    cases = [(100, 100, 0.25, 0.05, 0.20), (87, 103, 1.5, 0.02, 0.45), (50, 50, 0.01, 0.0, 0.10)]
    for S, K, T, r, sigma in cases:
        call = OptionsPricing.black_scholes(S, K, T, r, sigma, "call")
        put = OptionsPricing.black_scholes(S, K, T, r, sigma, "put")
        assert call - put == pytest.approx(S - K * math.exp(-r * T), abs=1e-10)


def test_invalid_option_type_raises():
    with pytest.raises(ValueError):
        OptionsPricing.black_scholes(100, 100, 0.25, 0.05, 0.2, "bad")


# --------------------------------------------------------------------------- #
# Greeks vs. finite difference of the pricer
# --------------------------------------------------------------------------- #

_CASES = [
    (100, 100, 0.25, 0.05, 0.20, "call"),
    (100, 100, 0.25, 0.05, 0.20, "put"),
    (105, 100, 0.5, 0.03, 0.30, "call"),
    (95, 100, 0.5, 0.03, 0.30, "put"),
    (120, 100, 0.08, 0.05, 0.60, "call"),
]


@pytest.mark.parametrize("S,K,T,r,sigma,option_type", _CASES)
def test_delta_matches_finite_difference(S, K, T, r, sigma, option_type):
    h = 1e-4
    fd = (OptionsPricing.black_scholes(S + h, K, T, r, sigma, option_type)
          - OptionsPricing.black_scholes(S - h, K, T, r, sigma, option_type)) / (2 * h)
    assert GreeksCalculator.delta(S, K, T, r, sigma, option_type) == pytest.approx(fd, abs=1e-6)


@pytest.mark.parametrize("S,K,T,r,sigma,option_type", _CASES[:3])
def test_gamma_matches_finite_difference(S, K, T, r, sigma, option_type):
    h = 0.05
    fd = (OptionsPricing.black_scholes(S + h, K, T, r, sigma, option_type)
          - 2 * OptionsPricing.black_scholes(S, K, T, r, sigma, option_type)
          + OptionsPricing.black_scholes(S - h, K, T, r, sigma, option_type)) / (h ** 2)
    assert GreeksCalculator.gamma(S, K, T, r, sigma, option_type) == pytest.approx(fd, rel=1e-4)


@pytest.mark.parametrize("S,K,T,r,sigma,option_type", _CASES[:3])
def test_vega_matches_finite_difference(S, K, T, r, sigma, option_type):
    h = 1e-5
    fd = (OptionsPricing.black_scholes(S, K, T, r, sigma + h, option_type)
          - OptionsPricing.black_scholes(S, K, T, r, sigma - h, option_type)) / (2 * h) / 100.0
    assert GreeksCalculator.vega(S, K, T, r, sigma, option_type) == pytest.approx(fd, rel=1e-5)


@pytest.mark.parametrize("S,K,T,r,sigma,option_type", _CASES[:3])
def test_theta_matches_finite_difference(S, K, T, r, sigma, option_type):
    h = 1e-5
    fd = -(OptionsPricing.black_scholes(S, K, T + h, r, sigma, option_type)
           - OptionsPricing.black_scholes(S, K, T - h, r, sigma, option_type)) / (2 * h) / 365.0
    assert GreeksCalculator.theta(S, K, T, r, sigma, option_type) == pytest.approx(fd, rel=1e-4)


@pytest.mark.parametrize("S,K,T,r,sigma,option_type", _CASES[:2])
def test_rho_matches_finite_difference(S, K, T, r, sigma, option_type):
    h = 1e-5
    fd = (OptionsPricing.black_scholes(S, K, T, r + h, sigma, option_type)
          - OptionsPricing.black_scholes(S, K, T, r - h, sigma, option_type)) / (2 * h) / 100.0
    assert GreeksCalculator.rho(S, K, T, r, sigma, option_type) == pytest.approx(fd, rel=1e-4)


def test_charm_matches_mixed_finite_difference_of_pricer():
    S, K, T, r, sigma = 100.0, 100.0, 0.25, 0.05, 0.20
    hS, hT = 0.05, 1e-4
    # d^2V/dS dT via a mixed central difference == dDelta/dT
    mixed = (OptionsPricing.black_scholes(S + hS, K, T + hT, r, sigma, "call")
             - OptionsPricing.black_scholes(S + hS, K, T - hT, r, sigma, "call")
             - OptionsPricing.black_scholes(S - hS, K, T + hT, r, sigma, "call")
             + OptionsPricing.black_scholes(S - hS, K, T - hT, r, sigma, "call")) / (4 * hS * hT)
    fd_charm = -mixed / 365.0  # charm := -dDelta/dT / 365
    assert GreeksCalculator.charm(S, K, T, r, sigma, "call") == pytest.approx(fd_charm, rel=1e-3)


def test_vanna_matches_mixed_finite_difference_of_pricer():
    S, K, T, r, sigma = 100.0, 100.0, 0.25, 0.05, 0.20
    hS, hV = 0.05, 1e-4
    mixed = (OptionsPricing.black_scholes(S + hS, K, T, r, sigma + hV, "call")
             - OptionsPricing.black_scholes(S + hS, K, T, r, sigma - hV, "call")
             - OptionsPricing.black_scholes(S - hS, K, T, r, sigma + hV, "call")
             + OptionsPricing.black_scholes(S - hS, K, T, r, sigma - hV, "call")) / (4 * hS * hV)
    assert GreeksCalculator.vanna(S, K, T, r, sigma, "call") == pytest.approx(mixed / 100.0, rel=1e-3)


def test_volga_matches_second_difference_of_pricer():
    S, K, T, r, sigma = 100.0, 100.0, 0.25, 0.05, 0.20
    h = 1e-3
    second = (OptionsPricing.black_scholes(S, K, T, r, sigma + h, "call")
              - 2 * OptionsPricing.black_scholes(S, K, T, r, sigma, "call")
              + OptionsPricing.black_scholes(S, K, T, r, sigma - h, "call")) / (h ** 2)
    assert GreeksCalculator.volga(S, K, T, r, sigma, "call") == pytest.approx(second / 100.0, rel=1e-3)


def test_put_call_charm_and_vanna_are_equal():
    # delta_put = delta_call - 1 (a constant offset), so d/dT and d/dsigma match exactly.
    S, K, T, r, sigma = 100.0, 100.0, 0.25, 0.05, 0.20
    assert GreeksCalculator.charm(S, K, T, r, sigma, "call") == pytest.approx(
        GreeksCalculator.charm(S, K, T, r, sigma, "put"), abs=1e-12)
    assert GreeksCalculator.vanna(S, K, T, r, sigma, "call") == pytest.approx(
        GreeksCalculator.vanna(S, K, T, r, sigma, "put"), abs=1e-12)


# --------------------------------------------------------------------------- #
# Implied volatility round-trip
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("sigma_true,option_type", [(0.15, "call"), (0.35, "call"), (0.60, "put"), (0.10, "put")])
def test_implied_volatility_round_trips(sigma_true, option_type):
    S, K, T, r = 100.0, 105.0, 0.5, 0.04
    price = OptionsPricing.black_scholes(S, K, T, r, sigma_true, option_type)
    iv = OptionsPricing.implied_volatility(price, S, K, T, r, option_type)
    round_trip_price = OptionsPricing.black_scholes(S, K, T, r, iv, option_type)
    assert round_trip_price == pytest.approx(price, abs=1e-8)
    assert iv == pytest.approx(sigma_true, abs=1e-6)


# --------------------------------------------------------------------------- #
# Binomial / Monte Carlo convergence to Black-Scholes for European options
# --------------------------------------------------------------------------- #


def test_binomial_converges_to_black_scholes_for_european():
    S, K, T, r, sigma = 100.0, 100.0, 0.25, 0.05, 0.20
    for option_type in ("call", "put"):
        bs = OptionsPricing.black_scholes(S, K, T, r, sigma, option_type)
        binomial = OptionsPricing.binomial_price(S, K, T, r, sigma, option_type, american=False, n_steps=500)
        assert binomial == pytest.approx(bs, abs=5e-3)


def test_monte_carlo_converges_to_black_scholes_for_european():
    S, K, T, r, sigma = 100.0, 100.0, 0.25, 0.05, 0.20
    for option_type in ("call", "put"):
        bs = OptionsPricing.black_scholes(S, K, T, r, sigma, option_type)
        mc = OptionsPricing.monte_carlo_price(S, K, T, r, sigma, option_type, n_paths=200_000, seed=42)
        assert mc["ci_95_lower"] - 0.05 <= bs <= mc["ci_95_upper"] + 0.05


def test_american_put_is_worth_at_least_european_put():
    S, K, T, r, sigma = 100.0, 110.0, 1.0, 0.05, 0.25
    euro = OptionsPricing.binomial_price(S, K, T, r, sigma, "put", american=False, n_steps=300)
    amer = OptionsPricing.binomial_price(S, K, T, r, sigma, "put", american=True, n_steps=300)
    assert amer >= euro - 1e-9


# --------------------------------------------------------------------------- #
# Boundary behaviour: T -> 0, deep ITM/OTM
# --------------------------------------------------------------------------- #


def test_boundary_T_to_zero_is_intrinsic():
    assert OptionsPricing.black_scholes(105, 100, 0.0, 0.05, 0.20, "call") == pytest.approx(5.0)
    assert OptionsPricing.black_scholes(95, 100, 0.0, 0.05, 0.20, "call") == pytest.approx(0.0)
    assert OptionsPricing.black_scholes(95, 100, 0.0, 0.05, 0.20, "put") == pytest.approx(5.0)
    assert GreeksCalculator.delta(105, 100, 0.0, 0.05, 0.20, "call") == pytest.approx(1.0)
    assert GreeksCalculator.delta(95, 100, 0.0, 0.05, 0.20, "call") == pytest.approx(0.0)
    assert GreeksCalculator.gamma(105, 100, 0.0, 0.05, 0.20) == 0.0


def test_deep_itm_call_behaves_like_forward():
    S, K, T, r, sigma = 1000.0, 10.0, 0.25, 0.05, 0.20
    price = OptionsPricing.black_scholes(S, K, T, r, sigma, "call")
    assert price == pytest.approx(S - K * math.exp(-r * T), abs=1e-6)
    assert GreeksCalculator.delta(S, K, T, r, sigma, "call") == pytest.approx(1.0, abs=1e-9)
    assert GreeksCalculator.gamma(S, K, T, r, sigma, "call") == pytest.approx(0.0, abs=1e-6)


def test_deep_otm_call_is_worthless():
    S, K, T, r, sigma = 10.0, 1000.0, 0.25, 0.05, 0.20
    price = OptionsPricing.black_scholes(S, K, T, r, sigma, "call")
    assert price == pytest.approx(0.0, abs=1e-9)
    assert GreeksCalculator.delta(S, K, T, r, sigma, "call") == pytest.approx(0.0, abs=1e-9)


def test_deep_itm_put_mirrors_call():
    S, K, T, r, sigma = 10.0, 1000.0, 0.25, 0.05, 0.20  # deep ITM put
    price = OptionsPricing.black_scholes(S, K, T, r, sigma, "put")
    assert price == pytest.approx(K * math.exp(-r * T) - S, abs=1e-6)
    assert GreeksCalculator.delta(S, K, T, r, sigma, "put") == pytest.approx(-1.0, abs=1e-9)


# --------------------------------------------------------------------------- #
# Strategy Builder
# --------------------------------------------------------------------------- #


def test_bull_call_spread_matches_hand_computed_bounds():
    result = StrategyBuilder.bull_call_spread(
        "SPY", S=100, K_long=100, K_short=110, T=0.25, r=0.05, sigma=0.20
    ).analyse()
    assert result.max_profit == pytest.approx(10 + result.net_premium, abs=1e-9)
    assert result.max_loss == pytest.approx(result.net_premium, abs=1e-9)
    assert result.net_premium < 0  # debit spread
    assert 0.0 <= result.probability_of_profit <= 1.0


def test_iron_condor_credit_and_bounds():
    result = StrategyBuilder.iron_condor(
        "SPX", S=4000, K_put_long=3800, K_put_short=3900,
        K_call_short=4100, K_call_long=4200, T=0.25, r=0.05, sigma=0.18,
    ).analyse()
    assert result.net_premium > 0  # net credit
    assert result.max_profit == pytest.approx(result.net_premium, abs=1e-9)
    assert result.max_loss < 0


def test_long_straddle_breakevens_symmetric_around_strike():
    result = StrategyBuilder.long_straddle("AAPL", S=150, K=150, T=0.25, r=0.05, sigma=0.35).analyse()
    lo, hi = result.breakeven_prices
    assert 150 - lo == pytest.approx(hi - 150, abs=1e-9)
    assert result.max_profit == float("inf")


# --------------------------------------------------------------------------- #
# Volatility Surface
# --------------------------------------------------------------------------- #


def _surface_df():
    return pd.DataFrame({
        "strike": [90, 95, 100, 105, 110, 90, 95, 100, 105, 110],
        "expiry_days": [30] * 5 + [60] * 5,
        "iv": [0.25, 0.22, 0.20, 0.21, 0.23, 0.27, 0.24, 0.22, 0.23, 0.25],
    })


def test_iv_rank_percentile():
    hist = pd.Series(np.linspace(0.10, 0.40, 252))
    result = VolatilitySurface.iv_rank(current_iv=0.30, historical_ivs=hist)
    expected_rank = float((hist < 0.30).mean() * 100)
    assert result["iv_rank"] == pytest.approx(expected_rank, abs=0.1)


def test_no_arbitrage_flat_surface_is_clean():
    vs = VolatilitySurface(_surface_df())
    result = vs.validate_no_arbitrage()
    assert result["arbitrage_free"] is True


def test_no_arbitrage_detects_calendar_inversion():
    df = pd.DataFrame({"strike": [100, 100], "expiry_days": [30, 60], "iv": [0.40, 0.10]})
    vs = VolatilitySurface(df)
    result = vs.validate_no_arbitrage()
    assert result["arbitrage_free"] is False
    assert result["n_violations"] == 1


# --------------------------------------------------------------------------- #
# Option Screener
# --------------------------------------------------------------------------- #


def test_option_screener_filters_by_delta_and_dte():
    chain = pd.DataFrame({
        "strike": [90, 95, 100, 105, 110],
        "expiry_days": [30, 30, 30, 45, 60],
        "iv": [0.22, 0.21, 0.20, 0.21, 0.23],
    })
    screener = OptionScreener(chain, underlying_price=100.0, r=0.05)
    candidates = screener.screen(min_dte=30, max_dte=45, min_delta=0.0, max_delta=1.0, option_type="put")
    assert set(candidates["expiry_days"]) <= {30, 45}

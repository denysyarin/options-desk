---
name: options-trading
description: "Full options trading: Black-Scholes pricing, Greeks, IV surface, multi-leg strategies, and option screening. USE FOR: options, black-scholes, greeks, delta, gamma, theta, vega, implied volatility, iron condor, straddle, strangle, call, put, option chain."
related_skills:
  - technical-analysis
  - risk-and-portfolio
  - statistics-timeseries
  - portfolio-optimization
tags:
  - trading
  - asset-class
  - options
  - greeks
  - iv
  - multi-leg
  - volatility
skill_level: advanced
kind: reference
category: trading/asset-classes
status: active
---
> **Skill:** Options Trading  |  **Domain:** trading  |  **Category:** asset-class  |  **Level:** advanced
> **Tags:** `trading`, `asset-class`, `options`, `greeks`, `iv`, `multi-leg`, `volatility`

---

## Daily desk (read this first on iPhone)

Do **not** scrape Finviz from a chat. Python + GitHub Actions already did.

**Never ask the human for `FINVIZ_AUTH_TOKEN`.** Never print it, never put it in chat, never request it as unblocking help. The token lives only in GitHub Actions secrets and the human’s local `.env`. You are not the Finviz client.

Universe is `config/watchlist.txt` (names you are willing to be assigned). Rank still discovers the trade inside that list.

1. Open the latest `snapshots/YYYY-MM-DD/rth/brief.md` (and `ranked.csv`). That is the trade list (top 5 by month vol, then VRP).
2. If `rth/meta.json` `fetched_at` is not **today America/New_York**, the snapshot is stale. Say so. Do not treat it as live.
3. Also check provenance: overnight/premarket tickers should intersect `config/watchlist.txt`, and RTH `meta.json` should include `chain_mode` (`top5` or `all_watchlist`). Date-fresh alone is not enough if the files were written by a pre-watchlist code path.
4. Trust Python numbers. Rank is VRP, then annualized RoC, then spread — never raw premium.
5. Gap / who-to-watch lives in `snapshots/*/premarket/snapshot.csv` (9:15 prelayer). Overnight RV lives in the previous session’s `snapshots/*/overnight/rv.json`.
6. Optional narrative: `prompts/daily-desk-analyst.md`. The standing GitHub issue is the inbox.

**If snapshots are missing or stale (phone / web / container):** do not ask for a token. Tell the human to either (a) open GitHub Actions and `workflow_dispatch` `overnight` / `premarket` / `rth` with `force=true`, or (b) wait for the weekday clock. Then analyze whatever brief lands in git / the standing issue.

**If the human asks to dump / chain / rank the full watchlist** and you are on a machine that already has `.env` with the token (presence only — never echo it):

```bash
python -m xtrading.screener rth --force --all-watchlist
```

Writes `snapshots/T/rth-full/`. Do not overwrite `rth/`. Do not commit unless asked. Do not comment it on the standing issue. If `.env` / token is absent in *this* runtime: do not ask for the value — say “run that command on the Mac with `.env`, or skip; I will score committed snapshots only.”

---

## Options Trading Skill

### Overview
Complete options pricing and strategy analysis toolkit. Implements Black-Scholes (1973) pricing,
all five first-order Greeks plus second-order (charm, vanna, volga), implied volatility extraction,
multi-leg strategy payoff analysis, IV surface construction, and option chain screening.

### Python Module
`xtrading/skills/options.py` — **this module exists in this repo and is unit-tested.**
See `tests/test_options.py` (40 tests, all passing). Every worked example below was generated
by actually running the code, not hand-typed. Put-call parity is verified to 1e-10, every Greek
is checked against a central finite difference of the pricer (second-order Greeks — charm, vanna,
volga — against a mixed/second finite difference of the pricer itself, not against another Greek),
the Brent-solved IV round-trips through the pricer, and binomial/Monte Carlo converge to
Black-Scholes for European options. Run with `python -m pytest tests/test_options.py -v` from the
repo root.

> **Provenance note:** an earlier version of this file had a different worked-example value for
> nearly every call (price, delta, theta, IV, and the second-order Greeks) than what the module's
> own formulas produce. The formulas were always correct; the `# →` comments were fabricated. Do
> not hand-type example outputs into this file again — regenerate them from the module and paste
> the real result.

### Stack
- **scipy.stats.norm** — Black-Scholes d1/d2 cumulative normal / density
- **scipy.optimize.brentq** — Implied volatility root finding
- **numpy** — Vectorised payoff calculations and Monte Carlo
- **pandas** — Option chain and surface management

---

## 1. Options Pricing — Black-Scholes

```python
from xtrading.skills.options import OptionsPricing

# European call price
price = OptionsPricing.black_scholes(S=100, K=100, T=0.25, r=0.05, sigma=0.20, option_type="call")
# → 4.614997129602855

# Put-call parity holds to 1e-10:
# call - put == S - K * exp(-rT)

# Implied volatility (Brent solver)
iv = OptionsPricing.implied_volatility(
    market_price=5.0, S=100, K=100, T=0.25, r=0.05, option_type="call"
)
# → 0.21958782684811157  (≈21.96% IV — a $5.00 market price on a $100 ATM call
#   implies MORE vol than the 20% used to price it at $4.61 above)

# Binomial tree (American options)
am_put = OptionsPricing.binomial_price(
    S=100, K=100, T=0.25, r=0.05, sigma=0.20, option_type="put", american=True
)
# → 3.478563175201223  (n_steps=400 default)

# Monte Carlo with confidence interval
mc = OptionsPricing.monte_carlo_price(S=100, K=100, T=0.25, r=0.05, sigma=0.20, n_paths=100_000, seed=7)
# → {"price": 4.595595457733976, "std_error": 0.020811611342406555,
#    "ci_95_lower": 4.55480469950286, "ci_95_upper": 4.636386215965093}
# (seeded here for a reproducible doc example; the black_scholes closed-form price
#  of 4.615 sits inside this CI, as tested in test_monte_carlo_converges_to_black_scholes_for_european)
```

---

## 2. Greeks Calculator

Scaling conventions (see the module docstring for the full rationale — pick one, then be
consistent): **delta/gamma** are raw; **theta** is per calendar day; **vega/rho/vanna** are per
1 percentage point of IV or rate; **charm** is per calendar day; **volga** is the derivative of
the already-scaled vega. Charm and vanna are mathematically identical for calls and puts (proven
in `test_put_call_charm_and_vanna_are_equal`), since `delta_put = delta_call - 1` is a constant
offset with zero time- or vol-derivative.

```python
from xtrading.skills.options import GreeksCalculator

# All Greeks in one call
greeks = GreeksCalculator.all_greeks(S=100, K=100, T=0.25, r=0.05, sigma=0.20, option_type="call")
# {
#   "price": 4.614997129602855, "delta": 0.5694601832076737, "gamma": 0.03928800094473793,
#   "theta": -0.028696304790426883, "vega": 0.19644000472368967, "rho": 0.13082755297791127,
#   "charm": -0.0003767342556344734, "vanna": -0.0014733000354276726, "volga": 0.012891375309992136,
#   "moneyness": "ATM", "intrinsic": 0.0, "time_value": 4.614997129602855
# }

# Individual Greeks
delta = GreeksCalculator.delta(S=105, K=100, T=0.25, r=0.05, sigma=0.20, option_type="call")
# → 0.7463032248822957 (ITM call, delta > 0.5)

gamma = GreeksCalculator.gamma(S=100, K=100, T=0.25, r=0.05, sigma=0.20)
# → 0.03928800094473793 (always positive)

theta = GreeksCalculator.theta(S=100, K=100, T=0.25, r=0.05, sigma=0.20, option_type="call")
# → -0.028696304790426883 per day (time decay)
```

---

## 3. Strategy Builder — Multi-Leg Analysis

`probability_of_profit` uses the standard textbook risk-neutral `N(d2)` convention (same one
`black_scholes` is built on) — it is not a physical-measure probability.

```python
from xtrading.skills.options import StrategyBuilder

# Bull Call Spread
builder = StrategyBuilder.bull_call_spread(
    symbol="SPY", S=100, K_long=100, K_short=110,
    T=0.25, r=0.05, sigma=0.20
)
result = builder.analyse()
# result.strategy_name = "Bull Call Spread"
# result.net_premium   = -3.423865465989781   (debit: negative)
# result.max_profit    = 6.576134534010219
# result.max_loss      = -3.423865465989781
# result.breakeven_prices = [103.4239]
# result.risk_reward   = 1.920675505311997
# result.probability_of_profit = 0.396793499956979

# Iron Condor
ic = StrategyBuilder.iron_condor(
    symbol="SPX", S=4000,
    K_put_long=3800, K_put_short=3900,
    K_call_short=4100, K_call_long=4200,
    T=0.25, r=0.05, sigma=0.18
)
result = ic.analyse()
# result.net_premium = 67.08892583075692  (credit)
# result.max_profit  = 67.08892583075692
# result.max_loss    = -32.91107416924308
# result.breakeven_prices = [3832.9111, 4167.0889]

# Long Straddle
straddle = StrategyBuilder.long_straddle(
    symbol="AAPL", S=150, K=150, T=0.25, r=0.05, sigma=0.35
)
result = straddle.analyse()
# Two breakeven prices: [129.1593, 170.8407]
# max_profit = inf (unbounded via the call leg)
```

---

## 4. Volatility Surface

`smile_at_expiry`'s "25d" wings are a documented **+/-10% strike-offset proxy**, not true
25-delta strikes — the surface schema below (`strike`, `expiry_days`, `iv`) doesn't carry
per-row deltas, so there's nothing to match a 25-delta strike against. See the returned `note`
field. `validate_no_arbitrage` only checks calendar-spread arbitrage (total variance
non-decreasing in T for a fixed strike); it does not check strike-dimension (butterfly/vertical)
arbitrage, which needs the underlying price to convert IV to price.

```python
import pandas as pd
from xtrading.skills.options import VolatilitySurface

# Build from option chain data
surface_data = pd.DataFrame({
    "strike": [90, 95, 100, 105, 110, 90, 95, 100, 105, 110],
    "expiry_days": [30]*5 + [60]*5,
    "iv": [0.25, 0.22, 0.20, 0.21, 0.23, 0.27, 0.24, 0.22, 0.23, 0.25],
})
vs = VolatilitySurface(surface_data)

# Smile at 30-day expiry
smile = vs.smile_at_expiry(expiry_days=30, atm_strike=100)
# {"atm_iv": 0.2, "skew_25d": -0.02, "butterfly_25d": 0.04, "bias": "put_skew",
#  "note": "wings are a +/-10% strike-offset proxy, not true 25-delta strikes"}

# Term structure
ts = vs.term_structure(atm_strike=100)
#    expiry_days  atm_iv  vix_equiv  annualised_cost_pct
# 0           30    0.20       20.0                 55.81
# 1           60    0.22       22.0                 43.41
# (annualised_cost_pct uses the Brenner-Subrahmanyam ATM-straddle approximation
#  0.8 * S * sigma * sqrt(T), expressed as %-of-spot and annualised — see docstring)

# IV Rank
import numpy as np
hist = pd.Series(np.linspace(0.10, 0.40, 252))
rank = vs.iv_rank(current_iv=0.30, historical_ivs=hist)
# {"iv_rank": 66.7, "regime": "NORMAL_IV", "strategy_bias": "NEUTRAL"}

# Arbitrage check (calendar spread only — see note above)
arb = vs.validate_no_arbitrage()
# {"arbitrage_free": True, "violations": [], "n_violations": 0}
```

---

## 5. Option Screener

Required `chain_df` columns: `strike`, `expiry_days`, `iv` — the screener prices and deltas each
row itself via `OptionsPricing`/`GreeksCalculator` using the underlying price and rate given at
construction, so a chain with pre-computed broker Greeks is not required. `probability_of_profit`
assumes a short-premium setup (the screener's stated purpose): it's `P(expires OTM)`.

```python
from xtrading.skills.options import OptionScreener

screener = OptionScreener(chain_df, underlying_price=100.0, r=0.05)

# Screen for short-premium setups (30-60 DTE, 0.20-0.45 |delta|)
candidates = screener.screen(
    min_pop=0.60, min_dte=30, max_dte=60,
    min_delta=0.20, max_delta=0.45,
    option_type="put",
)
#    strike  expiry_days     iv     delta     price  probability_of_profit
# 0    96.0           35   0.22 -0.240823  1.001059                0.737459
# 1    98.0           35   0.215 -0.341361  1.571058                0.633890
# (real chain_df used above: strikes 88-102, expiry_days=35, a put skew of
#  0.20-0.26 IV — a flatter chain with wide 2-point strike spacing can easily
#  produce ZERO rows in a narrow delta band; check candidates isn't empty
#  before assuming the screen "found nothing tradeable")

# Expected move calculation
em = screener.expected_move(expiry_days=35)
# {"expected_move_pts": 6.1932, "expected_move_pct": 6.1932,
#  "upper_bound": 106.1932, "lower_bound": 93.8068}
```

---

## Usage Conventions

1. **All prices** — same currency units as S and K
2. **T** — always in years (30 days = 30/365 = 0.082)
3. **sigma** — annualised decimal (20% = 0.20)
4. **r** — annualised risk-free rate decimal
5. **Theta** — returned as per-day (divide annual by 365 internally)
6. **Vega** — returned per 1% IV move (divide annual by 100 internally)
7. **Rho** — returned per 1% rate move (divide annual by 100 internally)
8. **Charm** — returned as per-day, identical for calls and puts
9. **Vanna** — returned per 1% IV move, identical for calls and puts
10. **Volga** — derivative of the already-scaled vega above, w.r.t. raw sigma
11. **Put-call parity** — always verified for European options (tested to 1e-10)
12. **`implied_volatility`** rejects a `market_price` below the *discounted* no-arbitrage floor
    (`max(S - K·e^(-rT), 0)` for calls, `max(K·e^(-rT) - S, 0)` for puts) — not the raw,
    undiscounted intrinsic value. A European put can legitimately price below `K - S` when the
    present value of `K` is meaningfully less than `K` itself; using raw intrinsic as the floor
    was a bug caught by the IV round-trip test on a deep-ITM put case.

## Key Formulas

```
Black-Scholes Call: S*N(d1) - K*exp(-rT)*N(d2)
Black-Scholes Put:  K*exp(-rT)*N(-d2) - S*N(-d1)
d1 = [ln(S/K) + (r + σ²/2)*T] / (σ*√T)
d2 = d1 - σ*√T

Delta (call) = N(d1)
Delta (put)  = N(d1) - 1
Gamma        = N'(d1) / (S*σ*√T)
Theta (call) = [-S*N'(d1)*σ/(2√T) - r*K*exp(-rT)*N(d2)] / 365
Theta (put)  = [-S*N'(d1)*σ/(2√T) + r*K*exp(-rT)*N(-d2)] / 365
Vega         = S*√T*N'(d1) / 100
Rho (call)   = K*T*exp(-rT)*N(d2) / 100
Rho (put)    = -K*T*exp(-rT)*N(-d2) / 100
Charm        = -N'(d1)*(2rT - d2*σ*√T) / (2*T*σ*√T) / 365       (same for call/put)
Vanna        = -N'(d1)*d2/σ / 100                                 (same for call/put)
Volga        = Vega_scaled * d1*d2/σ
```

---

## Related Skills

These companion skills exist in the upstream `mahmoud20138/Tradecraft` repo (`plugins/tradecraft/skills/`)
but are not yet vendored into this repo:

- Technical Analysis (`technical-analysis`)
- Risk And Portfolio (`risk-and-portfolio`)
- Statistical Analysis (`statistics-timeseries`)
- Portfolio Optimization (`portfolio-optimization`)

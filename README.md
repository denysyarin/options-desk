# options-desk

Options pricing and strategy analysis toolkit.

Python module: `xtrading/skills/options.py`  
Finviz adapter: `xtrading/data/finviz.py`  
Skill docs: `.claude/skills/options-trading/SKILL.md`

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then set FINVIZ_AUTH_TOKEN
python -m pytest tests/ -q
```

`FINVIZ_AUTH_TOKEN` is read from the environment. Never put it in code, commits, or logs. The Elite export URLs look like:

- options: `https://elite.finviz.com/export/options?t=MSFT&ty=oc&e=YYYY-MM-DD&auth=...`
- screener: `https://elite.finviz.com/export/screener?v=111&f=...&auth=...`

One export call per 60 seconds. Expired expiries (e.g. `e=2025-07-18`) return headers only.

## What's in here

- Black-Scholes pricing, implied vol, binomial tree, Monte Carlo
- First- and second-order Greeks
- Multi-leg strategy builder (spreads, iron condor, straddle)
- IV surface helpers and option-chain screening
- Finviz Elite chain + screener adapter behind a vendor-swappable `ChainProvider`
- Put-premium screener (`xtrading/screener/put_premium.py`): one Stage-1 custom Finviz export (`v=152&c=1,65,50,51,63,67,68` — price, weekly/monthly range vol, avg volume, earnings). Finviz has **no IV column and no 20-day prices**. IV comes only from Stage-2 option chains for the top 3 names (Friday expiries, 2–9 DTE). VRP uses annualized Finviz monthly high/low range as the realized-vol proxy.


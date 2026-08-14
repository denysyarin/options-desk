# options-desk

Options pricing and a weekday put-premium desk on Finviz Elite.

Python never asks a model for a rank. Claude / Cursor / OpenAI are optional narrators after the snapshot is already in git.

## Daily desk

Every weekday:

- **16:30 ET** overnight: screener + `/export/quote` for the top 20 → `snapshots/YYYY-MM-DD/overnight/rv.json`
- **09:15 ET** premarket: one Gap screener + options JSON for the top 3 → `brief.md` + comment on the standing GitHub issue

Clock: Cloudflare Worker (`infra/cloudflare-clock`). Muscle: GitHub Actions. Inbox: that issue. Analyst webhook is optional (`ANALYST_WEBHOOK_URL`).

```bash
python -m xtrading.screener overnight --force
python -m xtrading.screener premarket --force
```

Setup once: repo secret `FINVIZ_AUTH_TOKEN`, variable `DESK_GITHUB_ISSUE`, Worker secrets, watch the issue on your phone. Spec: `docs/superpowers/specs/2026-08-14-premarket-prelayer-design.md`.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then set FINVIZ_AUTH_TOKEN
python -m pytest tests/ -q
```

`FINVIZ_AUTH_TOKEN` is the Elite **export** API UUID in `auth=` on  
`https://elite.finviz.com/export/screener?...&auth=...` (same value works on `/export/quote`).  
Get it: Elite → Screener → **Export** → copy `auth=`. Docs: [api_explanation.ashx](https://elite.finviz.com/api_explanation.ashx).  
Not a login cookie, Google OAuth, or password. Never put it in git, logs, or a model vendor.

## What's in here

- Black-Scholes, Greeks, multi-leg strategies, IV surface, `OptionScreener`
- Finviz adapter (`xtrading/data/finviz.py`) behind `ChainProvider`
- Put-premium screener + scheduled jobs (`xtrading/screener/`)



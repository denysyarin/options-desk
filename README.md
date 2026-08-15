# options-desk

Options pricing and a weekday put-premium desk on Finviz Elite.

Python never asks a model for a rank. After RTH lands, Claude (skill + `prompts/daily-desk-analyst.md`) writes one short LOOK/IGNORE triage; dig deeper only on request.

## Daily desk

Every weekday:

- **16:30 ET** overnight: watchlist screener + `/export/quote` for up to 20 names (Finviz export cap) → `snapshots/YYYY-MM-DD/overnight/rv.json`
- **09:15 ET** premarket: one Gap screener for the watchlist → `snapshots/YYYY-MM-DD/premarket/snapshot.csv` (who gapped — not a trade list)
- **09:30 ET** RTH: live option JSON for the top 5 → `rth/brief.md` + comment on the standing GitHub issue
- right after RTH: Claude writes the short LOOK/IGNORE triage and pushes it to the phone via ntfy

Universe: `config/watchlist.txt`. Discovery ranking still runs inside that list.

Clock: Cloudflare Worker (`infra/cloudflare-clock`). Muscle: GitHub Actions. Inbox: that issue. Analyst webhook is optional (`ANALYST_WEBHOOK_URL`) and fires after the **RTH** commit.

```bash
python -m xtrading.screener overnight --force
python -m xtrading.screener premarket --force
python -m xtrading.screener rth --force
python -m xtrading.screener rth --force --all-watchlist   # agent/manual: every watchlist name → rth-full/
python -m xtrading.analyst --snapshot-dir snapshots/$(date +%F)/rth   # triage + ntfy push
```

## Triage + phone push

`xtrading.analyst` sends `rth/brief.md` and `prompts/daily-desk-analyst.md` to the Claude API, comments the LOOK/IGNORE triage on the standing issue, and pushes it to [ntfy](https://ntfy.sh). Both legs are optional and best-effort — the brief lands regardless.

| Setting | Where | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | repo secret | Without it you get a headline push, no triage |
| `ANTHROPIC_MODEL` | repo variable | Default `claude-sonnet-5` |
| `NTFY_TOPIC` | repo secret | On the public server the topic name **is** the password — use something unguessable |
| `NTFY_URL` | repo variable | Default `https://ntfy.sh` |
| `NTFY_TOKEN` | repo secret | Only for protected topics or a self-hosted server |
| `DESK_CLICK` | repo variable | `claude` (default) opens the Claude app with the triage prefilled; `issue` opens the GitHub issue |

Install the ntfy iOS app, subscribe to the same topic, and the triage arrives as a push. The triage is English-only; `ACT NOW` in it raises priority, otherwise it stays a normal notification.

Tapping the push opens `https://claude.ai/code/new?q=…&repo=denysyarin/options-desk` — the Claude **Code** tab in the browser (Safari / Claude web on iPhone is enough; the mobile app is not required). The triage is prefilled so you can send and dig in.

Setup once: repo secret `FINVIZ_AUTH_TOKEN`, variable `DESK_GITHUB_ISSUE`, Worker secrets, watch the issue on your phone. Specs: `docs/superpowers/specs/2026-08-14-premarket-prelayer-design.md`, `docs/superpowers/specs/2026-08-14-watchlist-universe-design.md`, `docs/superpowers/specs/2026-08-15-one-claude-triage-design.md`.

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



# Premarket prelayer + daily desk delivery

Date: 2026-08-14  
Status: implemented in repo; human setup (secrets, Worker, standing issue) still required  
Repo: `denysyarin/options-desk` (public — briefs will be public unless the repo is later made private)

## Goal

Every weekday the US cash session exists, this desk produces **data, a deterministic brief, and optional model narrative** — whether anyone opened an app or not.

You do not remember to run it. Interest is irrelevant. The archive is git + one GitHub issue you can scroll on the phone.

## Delivery (bulletproof split)

A model is optional narrative, not the clock, and not the Finviz client. If the analyst webhook is down or out of credits, the daily package still lands.

| Layer | Who | Every weekday? | If it dies |
|---|---|---|---|
| Clock | Cloudflare Worker, `*/15`, ET gate at 09:15 and 16:30 | Yes | cron-job.org posts the same `workflow_dispatch`; or manual `force` |
| Data + ranked puts | GitHub Actions + this repo’s Python + `FINVIZ_AUTH_TOKEN` | Yes | Nothing else calls Finviz. Retry / `force` dispatch |
| Deterministic brief | Python `brief.md` from the same job (VRP, gaps, earnings, flags) | Yes | N/A — same process as data |
| Inbox | One standing GitHub issue; the job **comments** the brief | Yes | Files still on `main` under `snapshots/` |
| Skill analysis | Optional **analyst webhook** fired *after* the premarket commit (Claude routine, Cursor agent, OpenAI, whatever is behind the URL) | Best effort | Issue already has the brief. Analyst never calls Finviz |

Two inboxes, same content spine:

1. **GitHub issue** (GitHub iOS app, email if you watch the repo) — always.
2. **Analyst session** (Claude / Cursor / OpenAI — whichever webhook is configured) — when that vendor is up.

Numbers never come from a model. Rank, Greeks, VRP, Gap, and the 60s export budget are Python. The webhook only gets `brief.md` + paths and may comment narrative. Swap vendors by changing `ANALYST_WEBHOOK_URL`; do not retune the screener.

Do not put `FINVIZ_AUTH_TOKEN` in any model vendor’s environment.

## Constraints

- Finviz Elite **`/export/*`**: one call per 60 seconds. Hard wait, retry that call once, then stop.
- Stock-page options JSON: not throttled. Use it for chains. CSV `/export/options` is fallback only.
- `/export/quote` is yesterday’s closes. Overnight only. Never at 9:15.
- Token only in GitHub Actions secrets and local `.env`. Never in git, Worker env, iOS Shortcuts, any model vendor env, logs, or `meta.json`.
- Model vendors are interchangeable and optional. A Claude routine schedule is a bad 9:15 clock (1-hour minimum, stagger, usage caps). If you use Claude, fire it from Actions via API trigger after the snapshot lands. Cursor mobile or OpenAI can replace that later with the same webhook payload.

## Clock vs muscle vs memory

| Piece | Role |
|---|---|
| Cloudflare Worker | Alarm only. Weekday 09:15 ET → `premarket.yml`. Weekday 16:30 ET → `overnight.yml`. |
| GitHub Actions | Python jobs, Finviz, commit snapshots, comment the standing issue, fire the analyst webhook. |
| `snapshots/YYYY-MM-DD/` on `main` | Durable archive. |
| Standing GitHub issue | Human inbox. One thread, newest comment is today. |
| Analyst webhook | Optional narrative on the same issue. Vendor-agnostic POST. |

GitHub `on.schedule` is not the clock (often 5–20 minutes late).

Manual wake: `workflow_dispatch` with `force=true`.

## Session rules

`xtrading/session.py`, timezone `America/New_York`.

- `job_for(now) -> "overnight" | "premarket" | "skip"`
- Premarket: weekday, 09:15 ET
- Overnight: weekday, 16:30 ET
- Weekend: skip
- Market holidays: still run; empty universe → `empty_universe: true`, comment “no liquid names”, no fake ranks
- Session date = ET calendar date, not UTC

Overnight on date **D** (session just closed) → `snapshots/D/overnight/`.

Premarket on date **T** → `snapshots/T/premarket/` and loads `rv.json` from the latest overnight date **strictly before T**, walking back at most 4 calendar days (Friday overnight → Monday premarket).

## Components

### `xtrading/session.py`

ET gate only. No I/O.

### `xtrading/screener/snapshots.py`

```
snapshots/YYYY-MM-DD/
  overnight/universe.csv
  overnight/rv.json
  overnight/meta.json
  premarket/snapshot.csv
  premarket/ranked.csv
  premarket/brief.md
  premarket/meta.json
```

Do not git-commit `overnight/history/*.csv` (too large). Optional 7-day Actions artifact.

`meta.json`: `fetched_at` (ISO ET), `job`, `n_export_calls`, `tickers`, `empty_universe`, `errors`, `rv_source`. No token.

### `xtrading/screener/brief.py`

Pure function: ranked frame + gap snapshot + meta → markdown.

Always includes:

- As-of timestamp (ET) and `rv_source`
- Top ranked cash-secured puts (VRP, then annualized RoC, then spread) — never raw premium
- Premarket Gap / rel volume for those tickers
- Earnings inside the DTE window (already hard-filtered out of ranks; still listed if present in the universe)
- Unreliable-IV flags, missing overnight RV, empty universe
- One-line “not advice; snapshot may be stale after 9:30 when Gap freezes”

### `xtrading/screener/jobs.py`

`run_overnight(...)` `run_premarket(...)`  
CLI: `python -m xtrading.screener overnight|premarket`

Print call plan before any export.

### `PutPremiumScreener`

Unchanged ranking. Premarket uses the Gap screener export. Morning never `fetch_history`. Top 3: `fetch_options_json` for listed 2–9 DTE. Missing RV → month range-vol.

### GitHub Actions

`overnight.yml` and `premarket.yml`.

- `workflow_dispatch` + `force`
- `concurrency: finviz-export` across both
- `contents: write`, `issues: write`
- Premarket after commit: comment `brief.md` on standing issue `DESK_GITHUB_ISSUE` (repo variable, created once)
- Then, if secrets `ANALYST_WEBHOOK_URL` and `ANALYST_WEBHOOK_TOKEN` exist, POST JSON `{ "date", "brief", "snapshot_dir" }` with `Authorization: Bearer`. Missing secrets → skip. `continue-on-error`. Payload is the Python brief, not a request to scrape Finviz.
- `FINVIZ_AUTH_TOKEN` required. Missing → fail before HTTP
- Push: rebase retry once, never `--force`

### Cloudflare Worker

`infra/cloudflare-clock/`. Cron `*/15 * * * *`. ET exact 09:15 / 16:30 weekdays only. Dispatch workflows, never `force`. Secrets: `GH_TOKEN` (Actions write on this repo only), `GH_OWNER`, `GH_REPO`.

cron-job.org is the documented spare clock.

### Analyst webhook (optional)

`prompts/daily-desk-analyst.md` is the prompt you paste into Claude / Cursor / OpenAI. The job POSTs the brief; the vendor is not in Python.

Prompt rules:

- Trust Python numbers in the payload. Do not re-rank by premium. Do not call Finviz.
- If `fetched_at` is not today ET, say stale and stop.
- Apply the options-trading skill: VRP, delta 0.10–0.25, DTE 2–9, earnings, spread, unreliable IV.
- Comment narrative on the standing GitHub issue if that connector exists.

## Screener columns and filters

View `v=152`.

Overnight columns: Ticker, Price, Vol Week, Vol Month, Avg Volume, Volume, Earnings. Expected ids `1,65,50,51,63,67,68`.

Premarket columns: Ticker, Price, Previous Close, Gap, Change, Change from Open, Rel Volume, Avg Volume, Volume, Vol Week, Vol Month, Earnings. Expected ids `1,65,81,61,66,60,64,63,67,50,51,68`. Pin whatever ids a live Elite header actually returns for those names.

Default filters (`FINVIZ_SCREENER_FILTERS` override): `sh_opt_option,sh_avgvol_o400,sh_price_o10`.

Overnight: top 20 by month range-vol then avg volume, then quote history.  
Premarket: one Gap export, chains for top 3 survivors.

## Export budget

Overnight: 1 + 20 exports ≈ 21 min.  
Premarket: 1 export. JSON unthrottled. Leave the rest of 9:15–9:30 unused for a retry.

## Failure modes

- Duplicate clock: `concurrency: finviz-export`; Worker only at exact 09:15 / 16:30
- Missed 9:15: `force=true` dispatch
- Partial overnight: keep finished tickers; morning does not quote-export
- Finviz 429: wait once, retry once, stop, commit what exists, comment the error
- Empty holiday: comment, no fake ranks
- Bad token: fail fast, redacted
- Analyst webhook down or credits exhausted: issue comment with `brief.md` still posted; fire step is best-effort (`continue-on-error`)
- Stale read: skill and routine both refuse to treat yesterday as live
- Public leak: token never in issue comments

## Tests (no network)

- Session gate including DST wall time in ET
- Overnight: 20 histories, no options JSON, 60s between quotes
- Premarket: Gap column, zero `fetch_history` when `rv.json` exists, top 3 JSON, `rv_source`
- `brief.md` from a fixture ranked table contains VRP, Gap, flags, and does not contain a fake token
- Missing overnight still briefs with `screener_month_vol`
- Redaction in logs and meta
- Snapshot “today” vs yesterday `fetched_at`

Not in CI: live Elite, Worker, Actions, the live routine. Manual: one `force` dispatch after secrets exist.

## Out of scope

macOS LaunchAgents, iOS as Finviz client, Telegram, NYSE holiday calendar, committing full quote CSVs, Worker-side Python, using any LLM scheduler as the 9:15 clock, putting the Elite token in a model vendor.

## Setup (human, once)

1. Repo secret `FINVIZ_AUTH_TOKEN`
2. Fine-grained PAT → Cloudflare `GH_TOKEN` / `GH_OWNER` / `GH_REPO`; `wrangler deploy`
3. Create standing issue “Options desk daily”; set repo variable `DESK_GITHUB_ISSUE`
4. Watch the repo or enable issue-comment notifications on that issue (this is how the phone nags you)
5. Optional: point `ANALYST_WEBHOOK_URL` / `ANALYST_WEBHOOK_TOKEN` at Claude, Cursor, or OpenAI using `prompts/daily-desk-analyst.md`. Skip this and the desk still delivers.
6. One `force` premarket dispatch; confirm commit + issue comment.

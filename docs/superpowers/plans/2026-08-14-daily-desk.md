# Daily Desk Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (this session: inline). Steps use checkbox syntax.

**Goal:** Weekday Finviz overnight RV + 9:15 premarket Gap screen, commit `brief.md`, comment a GitHub issue; optional vendor-agnostic analyst webhook.

**Architecture:** Python is the source of truth (rank, VRP, Greeks, 60s cap). Cloudflare Worker only dispatches Actions. A model webhook is optional POST after commit. GitHub issue is the inbox.

**Tech Stack:** Python 3.11, pytest, pandas, Finviz Elite, GitHub Actions, Cloudflare Worker cron.

## Global Constraints

- `/export/*` one call per 60 seconds; options JSON unthrottled
- Morning never calls `/export/quote`
- `FINVIZ_AUTH_TOKEN` never in git, logs, meta, model vendor env
- Session clock is `America/New_York`
- Default filters `sh_opt_option,sh_avgvol_o400,sh_price_o10`
- Overnight top 20; premarket chains top 3
- Analyst vendor is `ANALYST_WEBHOOK_URL` — Claude/Cursor/OpenAI interchangeable

---

### Task 1: Session gate

**Files:**
- Create: `xtrading/session.py`
- Test: `tests/test_session.py`

**Produces:** `job_for(now: datetime) -> Literal["overnight", "premarket", "skip"]`; `et_date(now) -> date`

- [ ] Tests for 09:15 ET weekday → premarket, 16:30 → overnight, 09:16/weekend → skip, DST wall time
- [ ] Implement
- [ ] Commit

### Task 2: Snapshot store + brief

**Files:**
- Create: `xtrading/screener/snapshots.py`, `xtrading/screener/brief.py`
- Test: `tests/test_snapshots.py`, `tests/test_brief.py`

**Produces:** `SnapshotStore(root)`; `load_latest_rv(before: date) -> tuple[date | None, dict[str, float]]`; `format_brief(ranked, snapshot, meta) -> str`

- [ ] Round-trip overnight/premarket files; walk back 4 days for RV; yesterday fetched_at is not today
- [ ] Brief contains VRP, Gap, rv_source, unreliable flag; no token
- [ ] Commit

### Task 3: Overnight + premarket jobs

**Files:**
- Create: `xtrading/screener/jobs.py`, `xtrading/screener/__main__.py`
- Modify: `xtrading/screener/put_premium.py` (columns, `pull_history`, `rv_override`)
- Test: `tests/test_jobs.py`

**Produces:** `run_overnight(...)`, `run_premarket(...)`; CLI `python -m xtrading.screener overnight|premarket`

- [ ] Overnight: 1 screener + 20 histories, no options JSON, writes rv.json
- [ ] Premarket: 1 Gap screener, zero fetch_history when rv.json exists, JSON for top 3, brief.md
- [ ] Missing overnight still runs with screener_month_vol
- [ ] Commit

### Task 4: Actions + Worker + prompt

**Files:**
- Create: `.github/workflows/overnight.yml`, `.github/workflows/premarket.yml`
- Create: `infra/cloudflare-clock/wrangler.toml`, `infra/cloudflare-clock/src/index.js`, `infra/cloudflare-clock/README.md`
- Create: `prompts/daily-desk-analyst.md`
- Modify: `.gitignore`, `.env.example`, `.claude/skills/options-trading/SKILL.md`, `README.md`

- [ ] Workflows: workflow_dispatch force, concurrency finviz-export, commit snapshots, gh issue comment, optional analyst POST
- [ ] Worker: */15, ET 09:15/16:30 weekday dispatch
- [ ] Commit

### Task 5: Verify

- [ ] `.venv/bin/python -m pytest tests/ -q`
- [ ] Push main

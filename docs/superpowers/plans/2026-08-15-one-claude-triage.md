# One Claude Triage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One short Claude LOOK/IGNORE triage on the existing RTH package — skill + prompt + brief enrichment; no second desk mode.

**Architecture:** Python keeps ranking CSP puts (VRP → RoC → spread) and adds `basis` to ranked/brief. Claude skill and analyst prompt rewrite the optional narrative into a ≤20-line bilingual triage. Watchlist drops NLR. Delivery stays GitHub issue + optional webhook.

**Tech Stack:** Python 3, pandas, pytest, markdown skill/prompt docs under `.claude/` and `prompts/`.

## Global Constraints

- No `snapshots/T/wheel/` or second screener job.
- Never ask for or print `FINVIZ_AUTH_TOKEN`.
- Trust Python numbers; Claude may re-prioritize LOOK but must not invent quotes.
- Spec: `docs/superpowers/specs/2026-08-15-one-claude-triage-design.md`.

---

### Task 1: Brief shows basis + RoC

**Files:**
- Modify: `xtrading/screener/put_premium.py`
- Modify: `xtrading/screener/brief.py`
- Modify: `tests/test_brief.py`
- Modify: `tests/test_put_premium.py` (if format_table / rank_rows assertions need `basis`)

- [ ] **Step 1: Failing test for brief columns**

In `tests/test_brief.py`, assert the brief markdown contains `basis` and `RoC` (or `annualized`) for a fixture row with known `mid`/`strike`.

- [ ] **Step 2: Run test — expect fail**

```bash
python -m pytest tests/test_brief.py -q
```

- [ ] **Step 3: Implement `basis` in `rank_rows`**

In `rank_rows`, after `breakeven` is set, also set `basis = strike - mid` (same value). Prefer writing both so CSV and skill share one name.

- [ ] **Step 4: Extend `format_brief` table**

Columns include: ticker, strike, DTE, mid, basis, RoC, delta, IV, 20d RV, VRP, Gap, flags.

- [ ] **Step 5: Tests pass**

```bash
python -m pytest tests/test_brief.py tests/test_put_premium.py -q
```

- [ ] **Step 6: Commit**

```bash
git add xtrading/screener/put_premium.py xtrading/screener/brief.py tests/test_brief.py tests/test_put_premium.py
git commit -m "feat(brief): expose basis and RoC for Claude triage"
```

---

### Task 2: Drop NLR from watchlist

**Files:**
- Modify: `config/watchlist.txt`

- [ ] **Step 1: Remove `NLR` line** from `config/watchlist.txt`.
- [ ] **Step 2: Commit** (or fold into Task 4 commit if preferred).

---

### Task 3: Skill + analyst prompt → LOOK/IGNORE

**Files:**
- Modify: `.claude/skills/options-trading/SKILL.md` (Daily desk section only)
- Modify: `prompts/daily-desk-analyst.md`

- [ ] **Step 1: Rewrite Daily desk section**

Replace “optional narrative” with: open latest RTH brief → write LOOK/IGNORE triage (bilingual template from spec) → dig deeper only if asked. Explicit: not positive-VRP-only; weigh premium, basis, RoC; ignore NLR-class; never invent ranks; never ask for Finviz token.

- [ ] **Step 2: Rewrite `prompts/daily-desk-analyst.md`**

Same template and rules. Max ~20 lines. Comment on standing issue if connector exists.

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/options-trading/SKILL.md prompts/daily-desk-analyst.md
git commit -m "docs(desk): Claude LOOK/IGNORE triage via skill and prompt"
```

---

### Task 4: Spec status + README pointer

**Files:**
- Modify: `docs/superpowers/specs/2026-08-15-one-claude-triage-design.md` (Status: implemented)
- Modify: `README.md` (one line on triage / link to spec)

- [ ] **Step 1: Mark spec implemented; add README link.**
- [ ] **Step 2: Full test suite**

```bash
python -m pytest tests/ -q
```

- [ ] **Step 3: Commit docs**

```bash
git add docs/superpowers/specs/2026-08-15-one-claude-triage-design.md docs/superpowers/plans/2026-08-15-one-claude-triage.md README.md config/watchlist.txt
git commit -m "docs: one Claude triage spec and watchlist drop NLR"
```

---

## Done when

- Brief has basis + RoC; tests green.
- Skill/prompt enforce short LOOK/IGNORE; dig-in on request.
- NLR gone from watchlist.
- No second desk mode introduced.

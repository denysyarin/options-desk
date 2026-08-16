# Clock Windows + Already-Wrote Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Late GitHub cron still runs the weekday job; a second run the same day no-ops if the done-file already exists; premarket fires at 09:00 ET.

**Architecture:** `job_for` becomes half-open ET windows instead of exact minutes. Each `run_*` job raises existing `SessionSkip` (exit 0) when the job’s complete artifact is already on disk, unless `force=True`. Worker and premarket cron move from 09:15 to 09:00. Dual UTC crons stay; the wrong-season hour remains outside the window.

**Tech Stack:** Python 3.11, pytest, Cloudflare Worker JS, GitHub Actions YAML.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-16-clock-window-design.md`
- Premarket fire 09:00 ET; window 09:00 ≤ t < 09:30
- RTH fire 09:30 ET; window 09:30 ≤ t < 10:00
- Overnight fire 16:30 ET; window 16:30 ≤ t < 17:00
- Already-wrote files: overnight `rv.json`, premarket `snapshot.csv`, rth `brief.md`
- `force=true` bypasses window and already-wrote
- `rth-full` / `--all-watchlist` is not the already-wrote check
- Skip stays exit 0 (`SessionSkip`); do not invent a second exception type
- Never ask for or print `FINVIZ_AUTH_TOKEN`
- Do not rewrite historical plans or old `snapshots/*/brief.md`
- Out of scope: holidays, red-X on skip, ntfy-on-miss, Greeks / sleeve
- Do not commit unless the human asked

---

### Task 1: `job_for` windows

**Files:**
- Modify: `xtrading/session.py`
- Test: `tests/test_session.py`

**Interfaces:**
- Consumes: `job_for(now: datetime) -> Literal["overnight", "premarket", "rth", "skip"]`
- Produces: same signature; weekday windows as in the spec (seconds ignored via hour+minute)

- [ ] **Step 1: Write the failing tests**

Replace `tests/test_session.py` so exact-minute tests become window tests. Keep DST winter coverage. `09:16` is no longer skip.

```python
"""America/New_York job gate for overnight vs premarket vs RTH."""
from datetime import datetime
from zoneinfo import ZoneInfo

from xtrading.session import et_date, job_for

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def test_weekday_0900_to_0929_et_is_premarket():
    assert job_for(datetime(2026, 8, 14, 9, 0, tzinfo=ET)) == "premarket"
    assert job_for(datetime(2026, 8, 14, 9, 14, tzinfo=ET)) == "premarket"
    assert job_for(datetime(2026, 8, 14, 9, 15, tzinfo=ET)) == "premarket"
    assert job_for(datetime(2026, 8, 14, 9, 29, tzinfo=ET)) == "premarket"


def test_weekday_0930_to_0959_et_is_rth():
    assert job_for(datetime(2026, 8, 14, 9, 30, tzinfo=ET)) == "rth"
    assert job_for(datetime(2026, 8, 14, 9, 31, tzinfo=ET)) == "rth"
    assert job_for(datetime(2026, 8, 14, 9, 59, tzinfo=ET)) == "rth"


def test_weekday_1630_to_1659_et_is_overnight():
    assert job_for(datetime(2026, 8, 14, 16, 30, tzinfo=ET)) == "overnight"
    assert job_for(datetime(2026, 8, 14, 16, 59, tzinfo=ET)) == "overnight"


def test_edges_outside_windows_are_skip():
    assert job_for(datetime(2026, 8, 14, 8, 59, tzinfo=ET)) == "skip"
    assert job_for(datetime(2026, 8, 14, 10, 0, tzinfo=ET)) == "skip"
    assert job_for(datetime(2026, 8, 14, 16, 29, tzinfo=ET)) == "skip"
    assert job_for(datetime(2026, 8, 14, 17, 0, tzinfo=ET)) == "skip"
    assert job_for(datetime(2026, 8, 15, 9, 0, tzinfo=ET)) == "skip"  # Saturday
    assert job_for(datetime(2026, 8, 16, 16, 30, tzinfo=ET)) == "skip"  # Sunday


def test_utc_that_is_not_in_et_window_is_skip():
    # 09:15 UTC in August is 05:15 ET
    assert job_for(datetime(2026, 8, 14, 9, 15, tzinfo=UTC)) == "skip"


def test_dst_winter_0900_et_still_premarket():
    assert job_for(datetime(2026, 1, 15, 9, 0, tzinfo=ET)) == "premarket"
    assert job_for(datetime(2026, 1, 15, 14, 0, tzinfo=UTC)) == "premarket"


def test_dst_winter_0930_et_still_rth():
    assert job_for(datetime(2026, 1, 15, 9, 30, tzinfo=ET)) == "rth"
    assert job_for(datetime(2026, 1, 15, 14, 30, tzinfo=UTC)) == "rth"


def test_et_date_uses_new_york_calendar():
    late_utc = datetime(2026, 8, 15, 3, 0, tzinfo=UTC)  # still Aug 14 in ET
    assert et_date(late_utc).isoformat() == "2026-08-14"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_session.py -v
```

Expected: FAIL on 09:00 / 09:14 / 09:29 / 09:31 / 09:59 / 16:59 (still exact-minute `job_for`).

- [ ] **Step 3: Implement windows in `job_for`**

In `xtrading/session.py`, replace the exact `hour ==` / `minute ==` checks with minutes-from-midnight:

```python
def job_for(now: datetime) -> JobName:
    local = _as_et(now)
    if local.weekday() >= 5:
        return "skip"
    hm = local.hour * 60 + local.minute
    if 9 * 60 <= hm < 9 * 60 + 30:
        return "premarket"
    if 9 * 60 + 30 <= hm < 10 * 60:
        return "rth"
    if 16 * 60 + 30 <= hm < 17 * 60:
        return "overnight"
    return "skip"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_session.py tests/test_jobs.py -q
```

Expected: PASS. Existing `test_jobs` still uses 09:15 as premarket and 09:30 as RTH — both still inside windows. `test_rth_wrong_window_skips` still uses 09:15, which is still not RTH.

- [ ] **Step 5: Commit** (skip unless the human asked)

---

### Task 2: Already-wrote no-op

**Files:**
- Modify: `xtrading/screener/jobs.py`
- Test: `tests/test_jobs.py`

**Interfaces:**
- Consumes: `run_overnight` / `run_premarket` / `run_rth`; `SessionSkip`; `SnapshotStore.day_dir`
- Produces: `_refuse_if_wrote(job, snapshot_root, now, force, *, all_watchlist=False) -> None` which raises `SessionSkip(f"already wrote {path}")` when the done-file exists and `force` is false. `--all-watchlist` skips this check.

Done files (ET date of `now()`):

| job | path |
|---|---|
| overnight | `{root}/{date}/overnight/rv.json` |
| premarket | `{root}/{date}/premarket/snapshot.csv` |
| rth | `{root}/{date}/rth/brief.md` |

Call `_refuse_if_wrote` immediately after `_require` in each runner. `run_rth` passes `all_watchlist=all_watchlist`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_jobs.py` (keep `PREMARKET_NOW` at 09:15 — still a valid premarket instant):

```python
def test_premarket_already_wrote_skips_without_finviz(tmp_path):
    p = DeskProvider()
    run_premarket(p, filters="f", snapshot_root=tmp_path, now=lambda: PREMARKET_NOW)
    p.calls.clear()
    with pytest.raises(SessionSkip, match="already wrote"):
        run_premarket(p, filters="f", snapshot_root=tmp_path, now=lambda: PREMARKET_NOW)
    assert p.calls == []


def test_overnight_already_wrote_skips_without_finviz(tmp_path):
    p = DeskProvider()
    run_overnight(p, filters="f", snapshot_root=tmp_path, now=lambda: OVERNIGHT_NOW, top_n=3)
    p.calls.clear()
    with pytest.raises(SessionSkip, match="already wrote"):
        run_overnight(p, filters="f", snapshot_root=tmp_path, now=lambda: OVERNIGHT_NOW, top_n=3)
    assert p.calls == []


def test_rth_already_wrote_skips_without_finviz(tmp_path):
    p = DeskProvider()
    run_overnight(p, filters="f", snapshot_root=tmp_path, now=lambda: OVERNIGHT_NOW, top_n=3)
    run_premarket(p, filters="f", snapshot_root=tmp_path, now=lambda: PREMARKET_NOW, top_n=3)
    run_rth(p, filters="f", snapshot_root=tmp_path, now=lambda: RTH_NOW, top_n=3)
    p.calls.clear()
    with pytest.raises(SessionSkip, match="already wrote"):
        run_rth(p, filters="f", snapshot_root=tmp_path, now=lambda: RTH_NOW, top_n=3)
    assert p.calls == []


def test_rth_partial_ranked_without_brief_runs_again(tmp_path):
    p = DeskProvider()
    day = tmp_path / "2026-08-14" / "rth"
    day.mkdir(parents=True)
    (day / "ranked.csv").write_text("ticker\nAAA\n")
    run_rth(p, filters="f", snapshot_root=tmp_path, now=lambda: RTH_NOW, top_n=3, force=True)
    assert (day / "brief.md").exists()
    assert any(c.startswith("chain:") for c in p.calls)


def test_force_reruns_even_when_done_file_exists(tmp_path):
    p = DeskProvider()
    run_premarket(p, filters="f", snapshot_root=tmp_path, now=lambda: PREMARKET_NOW)
    p.calls.clear()
    run_premarket(p, filters="f", snapshot_root=tmp_path, now=lambda: PREMARKET_NOW, force=True)
    assert any(c.startswith("screener:") for c in p.calls)


def test_rth_all_watchlist_ignores_existing_rth_brief(tmp_path):
    p = DeskProvider()
    run_overnight(p, filters="f", snapshot_root=tmp_path, now=lambda: OVERNIGHT_NOW, top_n=3)
    run_premarket(p, filters="f", snapshot_root=tmp_path, now=lambda: PREMARKET_NOW, top_n=3)
    run_rth(p, filters="f", snapshot_root=tmp_path, now=lambda: RTH_NOW, top_n=3)
    p.calls.clear()
    folder = run_rth(p, filters="f", snapshot_root=tmp_path, now=lambda: RTH_NOW, all_watchlist=True)
    assert folder.name == "rth-full"
    assert any(c.startswith("chain:") for c in p.calls)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_jobs.py::test_premarket_already_wrote_skips_without_finviz tests/test_jobs.py::test_force_reruns_even_when_done_file_exists -v
```

Expected: FAIL — second premarket hits Finviz instead of `SessionSkip`.

- [ ] **Step 3: Implement `_refuse_if_wrote`**

In `xtrading/screener/jobs.py`:

```python
_DONE_FILE = {
    "overnight": ("overnight", "rv.json"),
    "premarket": ("premarket", "snapshot.csv"),
    "rth": ("rth", "brief.md"),
}


def _refuse_if_wrote(
    job: str,
    snapshot_root: Path | str,
    now: Callable[[], datetime],
    force: bool,
    *,
    all_watchlist: bool = False,
) -> None:
    if force or all_watchlist:
        return
    spec = _DONE_FILE.get(job)
    if spec is None:
        return
    sub, name = spec
    path = SnapshotStore(snapshot_root).day_dir(et_date(now())) / sub / name
    if path.exists():
        raise SessionSkip(f"already wrote {path}")
```

Call after `_require(...)` in `run_overnight`, `run_premarket`, and `run_rth` (pass `all_watchlist=all_watchlist` only from `run_rth`).

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_jobs.py tests/test_session.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit** (skip unless the human asked)

---

### Task 3: Worker 09:00 + premarket cron + live copy

**Files:**
- Modify: `infra/cloudflare-clock/src/index.js`
- Modify: `infra/cloudflare-clock/README.md`
- Modify: `.github/workflows/premarket.yml`
- Modify: `.github/workflows/rth.yml` (description: window, not exact minute)
- Modify: `.github/workflows/overnight.yml` (description: window, not exact minute)
- Modify: `README.md`
- Modify: `.claude/skills/options-trading/SKILL.md`
- Modify: `prompts/daily-desk-analyst.md`
- Modify: `xtrading/screener/jobs.py` (module docstring + “using 9:15 snapshot” print)
- Modify: `xtrading/screener/brief.py`
- Modify: `tests/test_jobs.py` (module docstring)
- Modify: `docs/superpowers/specs/2026-08-14-premarket-prelayer-design.md` (one-line amended-by under the status line)
- Modify: `docs/superpowers/specs/2026-08-16-clock-window-design.md` (Status: `implemented`)
- Test: `tests/test_brief.py` (assert RTH tape says `9:00` not `9:15`)

**Interfaces:**
- Consumes: Task 1–2 behavior (unchanged)
- Produces: 09:00 fire in Worker + `0 13` / `0 14` UTC premarket cron; live strings say 9:00 prelayer

- [ ] **Step 1: Failing brief copy test**

In `tests/test_brief.py` `test_brief_includes_vrp_gap_source_and_flags_not_token`, add:

```python
    assert "9:00" in text
    assert "9:15" not in text
```

Add a premarket brief assertion (new test):

```python
def test_premarket_brief_names_0900_prelayer():
    text = format_brief(
        pd.DataFrame(),
        pd.DataFrame(),
        meta={"fetched_at": NOW.isoformat(), "job": "premarket", "rv_source": "none"},
    )
    assert "9:00" in text
    assert "9:15" not in text
```

- [ ] **Step 2: Run — expect fail**

```bash
python -m pytest tests/test_brief.py -v
```

Expected: FAIL on `9:15` still in tape.

- [ ] **Step 3: Update brief strings and the rest of the live copy**

`xtrading/screener/brief.py`:

- premarket tape: `"This is the 9:00 prelayer. Gap is live until 9:30 ET. Not a trade list."`
- rth tape: `"Cash is open. Chains are live. Gap is frozen from the 9:00 prelayer."`

`jobs.py` print: `"using 9:00 snapshot, options JSON (unthrottled)"`.

Worker: `if (hm === "09:00") workflow = "premarket.yml";`

`premarket.yml` cron:

```yaml
    - cron: "0 13 * * 1-5"
    - cron: "0 14 * * 1-5"
```

Description: `Run even outside the 09:00–09:29 ET window`.

`rth.yml` description: `Run even outside the 09:30–09:59 ET window`.

`overnight.yml` description: `Run even outside the 16:30–16:59 ET window`.

README / skill / analyst prompt / clock README: 09:15 → 09:00 for the premarket fire.

Prelayer spec: under Status, add:

```
Amended by: `docs/superpowers/specs/2026-08-16-clock-window-design.md` (premarket fire 09:00; session windows; already-wrote)
```

Do not rewrite the rest of that file. Do not edit `snapshots/2026-08-14/rth/brief.md`.

Clock-window spec Status → `implemented`.

- [ ] **Step 4: Run full suite**

```bash
python -m pytest tests/ -q
```

Expected: all pass.

- [ ] **Step 5: Commit** (skip unless the human asked)

**Human after merge:** `cd infra/cloudflare-clock && npx wrangler deploy` or Monday 09:00 never dispatches.

---

## Spec coverage (self-review)

| Spec requirement | Task |
|---|---|
| Premarket 09:00 fire + 09:00–09:29 window | 1, 3 |
| RTH 09:30–09:59 | 1 |
| Overnight 16:30–16:59 | 1 |
| Dual UTC crons kept | 3 (premarket hours moved, rth/overnight unchanged) |
| Already-wrote done-files | 2 |
| force bypasses both | 2 |
| Partial ranked.csv without brief.md re-runs | 2 |
| rth-full not the check | 2 |
| Skip exit 0 | 2 (reuse `SessionSkip`; `__main__.py` already prints and returns 0) |
| Worker 09:00 + premarket cron 0 13/14 | 3 |
| Live copy, not historical snapshots | 3 |
| DST tests | 1 |
| Out of scope left out | — |

# Watchlist Universe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pin the desk universe to `config/watchlist.txt`, export Finviz with `t=` + `sh_opt_option`, chain 5 names at RTH by default, and add `--all-watchlist` for an on-request full dump.

**Architecture:** A small `load_watchlist` parser is the source of truth. `FinvizProvider.fetch_screener` puts those tickers on `t=`. Jobs pass the list into every screener call. RTH writes `chain_mode` in meta; `--all-watchlist` skips the stage-1 cut and writes `snapshots/T/rth-full/` without touching `rth/`.

**Tech Stack:** Python 3.11, pytest, existing Finviz adapter and screener jobs.

## Global Constraints

- Universe is `config/watchlist.txt` in git; `FINVIZ_WATCHLIST` overrides the path only
- Screener `t=` is the watchlist; `f=sh_opt_option` only (drop avg-vol / price filters); `FINVIZ_SCREENER_FILTERS` may override `f=` but must not replace `t=`
- `OVERNIGHT_TOP_N = 20` is the Finviz `/export/quote` cap, not a product cap
- Clocked RTH and plain `rth` CLI: stage-1 cut to 5, then JSON, then VRP; `chain_mode=top5`
- `--all-watchlist` is RTH-only, JSON only, writes `rth-full/`, does not overwrite `rth/`, Actions never passes it
- Never print `FINVIZ_AUTH_TOKEN`; no network in tests
- Do not commit unless the human asks

---

### Task 1: Watchlist parser + starting list

**Files:**
- Create: `xtrading/screener/watchlist.py`
- Create: `config/watchlist.txt`
- Test: `tests/test_watchlist.py`

**Interfaces:**
- Consumes: a text file path
- Produces: `load_watchlist(path: str | Path) -> list[str]` — uppercase, first-seen unique, `#` comments, blanks ignored. Empty file → `[]`.

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path
from xtrading.screener.watchlist import load_watchlist

def test_load_watchlist_strips_comments_blanks_dupes_and_case(tmp_path):
    p = tmp_path / "w.txt"
    p.write_text(" spy \n# comment\nSNPS\n\nGOOG  # trailing\nspy\niren\n")
    assert load_watchlist(p) == ["SPY", "SNPS", "GOOG", "IREN"]

def test_load_watchlist_empty_file(tmp_path):
    p = tmp_path / "empty.txt"
    p.write_text("# only a comment\n\n")
    assert load_watchlist(p) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_watchlist.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Write minimal implementation**

`load_watchlist` reads the path, splits lines, strips `#...`, uppercases, skips blanks, drops duplicates preserving order.

`config/watchlist.txt` contains the 20 starting names from the spec (SPY through AMZN), one per line, with a one-line comment at the top.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_watchlist.py -v`
Expected: PASS

---

### Task 2: Finviz screener `t=` tickers

**Files:**
- Modify: `xtrading/data/finviz.py` (`fetch_screener`, `_screener_url`, `_load_or_fetch` screener branch)
- Test: `tests/test_finviz.py`

**Interfaces:**
- Consumes: `tickers: list[str] | None = None` on `fetch_screener`
- Produces: export URL with `t=SPY,SNPS,...` when tickers is non-empty; cache key includes the ticker set

- [ ] **Step 1: Write the failing tests**

```python
def test_screener_tickers_go_on_url_as_t(tmp_path):
    p = _provider(tmp_path, body=SCREENER_CSV)
    p.fetch_screener(filters="sh_opt_option", tickers=["SPY", "MSFT"])
    url = p._calls[0]
    assert "t=SPY%2CMSFT" in url or "t=SPY,MSFT" in url
    assert "f=sh_opt_option" in url

def test_screener_cache_key_includes_tickers(tmp_path):
    p = _provider(tmp_path, body=SCREENER_CSV)
    p.fetch_screener(filters="sh_opt_option", tickers=["AAPL"])
    p.fetch_screener(filters="sh_opt_option", tickers=["MSFT"])
    assert len(p._calls) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_finviz.py::test_screener_tickers_go_on_url_as_t tests/test_finviz.py::test_screener_cache_key_includes_tickers -v`
Expected: FAIL (unexpected keyword `tickers`)

- [ ] **Step 3: Write minimal implementation**

`fetch_screener(..., tickers=None)` adds `t=",".join(tickers)` to `extra` when tickers is non-empty. Cache key includes that `t` value. `_screener_url` reads `t` from extra (pass `t` through `_load_or_fetch` extra, same as `v`/`f`/`c`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_finviz.py -v`
Expected: PASS (including existing screener tests with `tickers=None`)

---

### Task 3: Jobs use watchlist, optionable-only filters, RTH top 5

**Files:**
- Modify: `xtrading/screener/jobs.py` (`DEFAULT_FILTERS`, `RTH_CHAIN_N`, `run_overnight` / `run_premarket` / `run_rth` signatures and `fetch_screener` calls, `chain_mode` in RTH meta)
- Modify: `xtrading/screener/__main__.py` (load watchlist, pass tickers, default filters)
- Modify: `xtrading/screener/put_premium.py` (`ASSUMPTIONS["top_n"] = 5`, pass `tickers` into `fetch_screener`)
- Test: `tests/test_jobs.py`
- Test: `tests/test_put_premium.py` (`test_run_prints_plan_before_any_fetch` must pass `top_n=3` so it still asserts BBB/CCC/DDD, **or** update expected set to five names)

**Interfaces:**
- Consumes: `load_watchlist`, `fetch_screener(..., tickers=)`
- Produces: `DEFAULT_FILTERS = "sh_opt_option"`; `RTH_CHAIN_N = 5`; jobs accept `tickers: list[str] | None = None` and pass them through; RTH meta `"chain_mode": "top5"`

- [ ] **Step 1: Write the failing tests**

In `tests/test_jobs.py`, make `DeskProvider.fetch_screener` record `tickers` in `self.calls` as `screener:{filters}:{','.join(tickers or [])}`.

```python
def test_overnight_passes_tickers_to_screener(tmp_path):
    p = DeskProvider()
    run_overnight(
        p, filters="sh_opt_option", snapshot_root=tmp_path,
        now=lambda: OVERNIGHT_NOW, top_n=3, tickers=["BBB", "CCC"],
    )
    assert any(c.startswith("screener:sh_opt_option:BBB,CCC") for c in p.calls)

def test_rth_default_chain_n_is_five():
    from xtrading.screener.jobs import RTH_CHAIN_N
    from xtrading.screener.put_premium import ASSUMPTIONS
    assert RTH_CHAIN_N == 5
    assert ASSUMPTIONS["top_n"] == 5
```

Add `chain_mode` assertion to `test_rth_uses_premarket_snapshot_overnight_rv_and_live_chains`: after `run_rth(...)`, `json.loads(meta)["chain_mode"] == "top5"`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_jobs.py::test_overnight_passes_tickers_to_screener tests/test_jobs.py::test_rth_default_chain_n_is_five -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

`DEFAULT_FILTERS = "sh_opt_option"`. `RTH_CHAIN_N = 5`. `ASSUMPTIONS["top_n"] = 5`.

Each `run_*` takes `tickers: list[str] | None = None` and passes it to `provider.fetch_screener(..., tickers=tickers)`. RTH meta includes `"chain_mode": "top5"`.

`__main__.py`: `WATCHLIST_PATH = os.environ.get("FINVIZ_WATCHLIST", "config/watchlist.txt")`, `tickers = load_watchlist(WATCHLIST_PATH)`, pass into runners.

`PutPremiumScreener.run` gains `tickers: list[str] | None = None` and passes it when it calls `fetch_screener`.

Keep existing job tests that pass explicit `top_n=3`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_jobs.py tests/test_put_premium.py tests/test_watchlist.py tests/test_finviz.py -v`
Expected: PASS

---

### Task 4: `--all-watchlist` writes `rth-full/`

**Files:**
- Modify: `xtrading/screener/snapshots.py` (`write_rth` job folder name, or `job="rth"` parameter)
- Modify: `xtrading/screener/jobs.py` (`run_rth(..., all_watchlist=False)`)
- Modify: `xtrading/screener/put_premium.py` (`all_watchlist` skips `stage1_top_tickers`, uses every `universe["Ticker"]`)
- Modify: `xtrading/screener/__main__.py` (`--all-watchlist`, reject on overnight/premarket)
- Test: `tests/test_jobs.py`
- Test: `tests/test_snapshots.py`

**Interfaces:**
- Consumes: `run_rth(..., all_watchlist: bool = False)`
- Produces: `snapshots/T/rth-full/{ranked.csv,brief.md,meta.json}` with `"chain_mode": "all_watchlist"`; official `rth/` untouched

- [ ] **Step 1: Write the failing tests**

```python
def test_rth_all_watchlist_writes_rth_full_and_leaves_rth_alone(tmp_path):
    p = DeskProvider()
    run_overnight(p, filters="f", snapshot_root=tmp_path, now=lambda: OVERNIGHT_NOW, top_n=3)
    run_premarket(p, filters="f", snapshot_root=tmp_path, now=lambda: PREMARKET_NOW, top_n=3)
    p.calls.clear()
    folder = run_rth(
        p, filters="f", snapshot_root=tmp_path, now=lambda: RTH_NOW,
        all_watchlist=True,
    )
    assert folder.name == "rth-full"
    assert (folder / "brief.md").exists()
    meta = json.loads((folder / "meta.json").read_text())
    assert meta["chain_mode"] == "all_watchlist"
    assert not (tmp_path / "2026-08-14" / "rth").exists()
    chained = {c.split(":")[1] for c in p.calls if c.startswith("chain:")}
    assert chained == {"AAA", "BBB", "CCC", "DDD", "EEE"}
```

`write_rth(..., job="rth-full")` round-trip in `tests/test_snapshots.py`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_jobs.py::test_rth_all_watchlist_writes_rth_full_and_leaves_rth_alone -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

`SnapshotStore.write_rth(..., job: str = "rth")` uses `_job_dir(d, job)`.

`PutPremiumScreener.run(..., all_watchlist: bool = False)`: if true, `tickers = [str(t) for t in universe["Ticker"].tolist()]`.

`run_rth`: if `all_watchlist`, pass that flag, set `chain_mode` accordingly, `write_rth(..., job="rth-full")`.

`__main__.py`: `--all-watchlist`; if set on a non-rth job, print error to stderr and return 2.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/ -q`
Expected: PASS

---

### Task 5: Docs, skill, env example, gitignore

**Files:**
- Modify: `README.md` (top 5, watchlist file, `--all-watchlist`)
- Modify: `.env.example` (filters default, `FINVIZ_WATCHLIST`)
- Modify: `.claude/skills/options-trading/SKILL.md` (daily desk: full-watchlist command; still never scrape HTML / print token)
- Modify: `.gitignore` (`snapshots/**/rth-full/`)

No production-code tests. Config files.

- [ ] **Step 1: Edit the four files to match the spec**

README daily desk: overnight still top 20 (Finviz cap); RTH top 5; universe is `config/watchlist.txt`; show `python -m xtrading.screener rth --force --all-watchlist`.

Skill daily desk add:

```
If the human asks to dump / chain / rank the full watchlist:
  python -m xtrading.screener rth --force --all-watchlist
Writes snapshots/T/rth-full/. Do not overwrite rth/. Do not commit unless asked.
Still never scrape Finviz HTML from chat. Never print FINVIZ_AUTH_TOKEN.
```

- [ ] **Step 2: Run full test suite**

Run: `python -m pytest tests/ -q`
Expected: PASS

---

## Spec coverage

| Spec requirement | Task |
|---|---|
| `config/watchlist.txt` parse rules + starting 20 | 1 |
| Finviz `t=` + `sh_opt_option`; filters override does not drop `t=` | 2, 3 |
| Overnight 20 Finviz cap unchanged | 3 (constant stays) |
| RTH default 5, `chain_mode=top5` | 3 |
| `--all-watchlist` → `rth-full/`, skill exception | 4, 5 |
| Actions never passes the flag | 5 (no workflow edit) |
| Docs / gitignore | 5 |

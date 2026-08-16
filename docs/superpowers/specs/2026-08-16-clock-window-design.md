# Clock windows + already-wrote (late GitHub cron)

Date: 2026-08-16  
Status: implemented  
Amends: `docs/superpowers/specs/2026-08-14-premarket-prelayer-design.md` (exact-minute gate, 09:15 fire)

## Goal

A weekday GitHub cron that starts **late** still runs the job it was meant for, instead of a green `session is 'skip'`. A second run the same morning (Worker on time, then late cron) does **not** hit Finviz again or double-comment / double-push.

Python remains the session gate. The Worker still does not send `force`.

## Locked decisions

| Choice | Decision |
|---|---|
| Premarket fire | **09:00 ET** (was 09:15). Worker already ticks `*/15`, so 09:00 is a real tick. |
| Premarket window | 09:00–09:29 ET inclusive of start, exclusive of 09:30 |
| RTH fire | 09:30 ET (unchanged) |
| RTH window | 09:30–09:59 ET |
| Overnight fire | 16:30 ET (unchanged) |
| Overnight window | 16:30–16:59 ET |
| Dual UTC crons | Keep both hours (EDT + EST). Wrong-season cron is ~1h off and **outside** these windows, so it still no-ops. |
| Second run | If today’s snapshot for **that job** already exists → no-op (no Finviz, no commit, no ntfy). |
| `force=true` | Bypasses the time window **and** the already-wrote check. |
| Skip exit | Wrong-window and already-wrote stay **exit 0** (green), same as today’s `SessionSkip`. |
| Out of scope | NYSE holidays, failing the job on skip, ntfy-on-miss, top-5 vs full watchlist, Greeks / $200k sleeve, a second data vendor. |

## Why 09:00, not a longer 09:15 window

Premarket and RTH are 15 minutes apart today. A 25-minute premarket window after 09:15 would collide with 09:30. Moving premarket to **09:00** gives a 30-minute backup window and leaves the 09:15 Worker tick unused (no-op). Late premarket that still misses 09:30 is unchanged: RTH falls back to one Gap screener.

## `job_for` windows

Weekday only (`weekday() < 5`). Compare ET hour:minute (seconds ignored).

| Local ET | Return |
|---|---|
| 09:00 ≤ t < 09:30 | `premarket` |
| 09:30 ≤ t < 10:00 | `rth` |
| 16:30 ≤ t < 17:00 | `overnight` |
| weekend or anything else | `skip` |

DST tests: 09:00 ET in August = 13:00 UTC; in January = 14:00 UTC. Same mapping for 09:30 / 16:30 as today.

## Already-wrote

Same America/New_York **calendar date** as `et_date(now())`. Existence of the job’s **complete** artifact:

| Job | File that means “done” |
|---|---|
| overnight | `snapshots/YYYY-MM-DD/overnight/rv.json` |
| premarket | `snapshots/YYYY-MM-DD/premarket/snapshot.csv` |
| rth | `snapshots/YYYY-MM-DD/rth/brief.md` |

Partial writes do not count (`ranked.csv` without `brief.md` → run again). `rth-full/` is manual (`--all-watchlist`) and is not this check.

Log one line (`already wrote …` / existing `SessionSkip` message) and return 0. Actions `git add snapshots` then “no snapshot changes.”

Concurrency `finviz-export` + `cancel-in-progress: false` stays: the late job waits, then sees the file and no-ops.

## Clock YAML / Worker

| Piece | Change |
|---|---|
| `infra/cloudflare-clock/src/index.js` | `09:15` → `09:00` |
| `.github/workflows/premarket.yml` | cron `15 13` / `15 14` → `0 13` / `0 14`; description “09:15” → “09:00” |
| `rth.yml` / `overnight.yml` | cron unchanged; descriptions can say “window” not “exact minute” |
| Worker secrets | Unchanged. Redeploy the Worker after the JS change or Monday 09:00 will never dispatch. |

## Copy that must move with the clock

Live docs and runtime strings (not historical plans, not old `snapshots/*/brief.md`):

- `README.md`, `.claude/skills/options-trading/SKILL.md`, `prompts/daily-desk-analyst.md`
- `xtrading/screener/jobs.py` docstring / “using 9:15 snapshot” print
- `xtrading/screener/brief.py` prelayer / RTH tape lines
- `infra/cloudflare-clock/README.md`
- This spec amends the 09:15 lines in `2026-08-14-premarket-prelayer-design.md` (short “amended by” note at the top is enough; do not rewrite that whole file)

## Tests (required)

- 09:00 / 09:14 / 09:29 → premarket; 09:30 / 09:59 → rth; 10:00 → skip
- 16:29 → skip; 16:30 / 16:59 → overnight; 17:00 → skip
- Weekend 09:00 still skip
- DST winter 09:00 ET still premarket
- Already-wrote: each job no-ops when the done-file exists; provider must not be called
- `force=true` with a done-file still calls the provider
- Existing wrong-window `SessionSkip` tests retargeted to times outside the new windows (e.g. 09:31 is now **rth**, not skip)

## Token / Finviz rules (unchanged)

Never ask for `FINVIZ_AUTH_TOKEN`. Already-wrote exists to **avoid** a second Elite pull, not to add a new client.

## Out of scope (repeat)

NYSE holiday calendar (already out of the 2026-08-14 prelayer spec). Red X on skip. Phone push when a job never ran. Greeks + $200k sleeve.

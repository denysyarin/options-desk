# Watchlist universe (wheel-eligible discovery)

Date: 2026-08-14  
Status: implemented in repo  
Amends: `docs/superpowers/specs/2026-08-14-premarket-prelayer-design.md` (screener filters, overnight cut, RTH chain count)

## Goal

The daily desk still **discovers** which cash-secured puts to sell (VRP, then annualized RoC, then spread). The universe is no longer “whatever Finviz’s volume/price filters return.” It is the names the trader is **willing to be assigned** — a wheel watchlist that will grow.

## Universe

Source of truth: `config/watchlist.txt` in git.

- One ticker per line.
- `#` starts a comment (full-line or trailing).
- Blank lines ignored.
- Case-insensitive; stored uppercase.
- First-seen order; duplicates dropped.
- Empty file after parse → `empty_universe: true`, same holiday path (comment, no fake ranks).

Starting list (20 names, first-seen from the 2026-08-14 paste):

```
SPY
SNPS
GOOG
NLR
IREN
MSFT
HLIO
ONTO
Q
APD
AVGO
NBIS
MMM
NVDA
GLD
MCD
DELL
AAPL
SPCX
AMZN
```

Changing the universe is editing this file. No GitHub secret or Actions variable for tickers. Optional env `FINVIZ_WATCHLIST` overrides the path (tests / local experiments only).

## Finviz call

One `/export/screener` per job that already exported a screener, with:

- `t=` = comma-joined watchlist (the universe)
- `f=sh_opt_option` so a name without listed options cannot rank
- same view/columns as today (`v=152`, overnight vs premarket column ids unchanged)

Drop `sh_avgvol_o400` and `sh_price_o10`. Those were discovery filters. They would kick names the trader already chose (e.g. HLIO). `FINVIZ_SCREENER_FILTERS` still overrides `f=` if set; it must not replace `t=`.

`FinvizProvider.fetch_screener` gains an optional `tickers` list and puts it on the URL as `t=`. Cache key includes the ticker set so a filter-only cache cannot be reused.

Jobs load the watchlist once and pass it into every `fetch_screener` (overnight, premarket, RTH fallback). `PutPremiumScreener.run` does the same when it fetches its own screener.

## Ranking (unchanged shape)

Still two cuts:

1. **Stage 1 (screener columns):** month range-vol, then avg volume.
2. **Stage 2 (live puts):** VRP, then annualized RoC, then spread. Delta 0.10–0.25, DTE 2–9, earnings hard-filter — existing put-premium rules.

The watchlist is the eligible set. Ranking still picks the trade.

## Overnight 20 is a Finviz cap

`OVERNIGHT_TOP_N = 20` stays. That is **not** “the desk only cares about 20 names.” It is today’s Finviz Elite `/export/*` budget: one call per 60 seconds, so 1 screener + 20 `/export/quote` ≈ 21 minutes.

- Watchlist length ≤ 20: quote history for every name that survived `sh_opt_option`.
- Watchlist length > 20: stage-1 cut to 20, then quote history for those. Discovery inside a larger willing-to-own set.
- When the data provider changes, this constant is what lifts. Do not invent a second product cap.

Premarket: one Gap export for the full `t=` list (one call, no 20-cut).

## RTH chains 5 (default)

`RTH_CHAIN_N` and `ASSUMPTIONS["top_n"]` go from 3 to **5**.

The **clocked** 09:30 job and a plain `python -m xtrading.screener rth` stay on the stage-1 cut. Not a full-watchlist dump:

1. Stage-1 cut to 5 names by month range-vol (from the watchlist snapshot).
2. Live options JSON for those 5 (unthrottled — 5 vs 3 is free).
3. Rank those puts by VRP.

JSON is not the Finviz export budget. Overnight quote-history is.

Zero `/export/*` when today’s premarket snapshot exists. Missing snapshot → one Gap export with the same `t=` list, then JSON for 5.

`meta.json` records `"chain_mode": "top5"`. GitHub Actions never passes the full-dump flag.

## Full-watchlist dump (agent / CLI only)

On request, an agent (or a human at the terminal) may skip the stage-1 cut and chain **every** watchlist name that survived `sh_opt_option`.

- Flag: `--all-watchlist` on the `rth` job only.
- Command: `python -m xtrading.screener rth --force --all-watchlist`
- Still uses today’s premarket Gap snapshot and overnight `rv.json`. Still no `/export/quote`. Options JSON only.
- Writes `snapshots/T/rth-full/` (`ranked.csv`, `brief.md`, `meta.json` with `"chain_mode": "all_watchlist"`). Does **not** overwrite `snapshots/T/rth/` (the official 09:30 brief).
- Do not commit `rth-full/` unless the human asks. Do not comment it on the standing issue.
- Overnight is unchanged: still Finviz-capped at 20 quote exports. This flag does not exist on overnight or premarket.

Skill (`options-trading` daily desk): if the human asks to dump / chain / rank the **full watchlist**, run that command only when local `.env` already has the token (presence check — never echo). Still never scrape Finviz HTML from chat, never print `FINVIZ_AUTH_TOKEN`, **never ask the human for the token**. If the runtime has no token, tell them to run the command on the Mac or use Actions; score committed snapshots only.

## What does not change

Clock, official `snapshots/T/rth/` layout, standing GitHub issue, analyst webhook, 60s export throttle, token redaction, session gates, brief format, Cloudflare Worker. The skill daily-desk section gains the `--all-watchlist` exception only.

## Tests (no network)

- Watchlist parse: comments, blanks, duplicates, case, empty file.
- Screener URL contains `t=` of the loaded list and `f=sh_opt_option`; cache key differs when tickers differ.
- Overnight still quote-exports `top_n` histories, never options JSON. Default overnight `top_n` remains 20 (Finviz cap).
- Premarket still one screener, zero history, zero chains, and receives tickers.
- RTH default `top_n` is 5, `chain_mode=top5`; uses premarket snapshot + overnight RV; zero `fetch_history`.
- `--all-watchlist` chains every universe ticker, writes `rth-full/`, leaves `rth/` untouched, `chain_mode=all_watchlist`.
- Existing brief / redaction / session tests still pass.

## Out of scope

New data provider, making the 09:30 clock dump the full list, NYSE holiday calendar, Finviz portfolio sync, auto-growing the list from a screener.

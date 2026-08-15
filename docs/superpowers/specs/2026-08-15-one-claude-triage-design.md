# One Claude triage report (not a second desk)

Date: 2026-08-15  
Status: implemented  
Amends: `docs/superpowers/specs/2026-08-14-premarket-prelayer-design.md` (analyst role), `docs/superpowers/specs/2026-08-14-watchlist-universe-design.md` (universe hygiene)

## Goal

After the existing Python RTH package lands, **one short Claude report** triages the book in advisor style: *look at this* / *ignore that*. The human requests deeper analysis only on names that look good. There is **no second desk mode**, no `snapshots/T/wheel/`, and no parallel screener job.

## Locked decisions

| Choice | Decision |
|---|---|
| Modes | One pipeline only (`overnight` → `premarket` → `rth`) |
| Author | Claude via `.claude/skills/options-trading` + `prompts/daily-desk-analyst.md` |
| Length | ≤ ~20 lines; LOOK / IGNORE / urgency; no essay |
| Language | Bilingual one-liners: English section headers; RU trading words OK (`страйк`, `сейчас`) |
| Delivery | Python `brief.md` → standing GitHub issue (unchanged). Claude triage via skill / optional analyst webhook → same issue or chat. No Telegram bot in v1. |
| NLR | Removed from `config/watchlist.txt` (deep-ITM hope puts are an anti-pattern) |
| Deeper analysis | On human request only (“dig into NBIS 205”) |

## What Claude must weigh (not “positive VRP only”)

Python still ranks the CSP table by **VRP → annualized RoC → spread**. Claude’s **LOOK** list may **re-prioritize** using wheel criteria, using only numbers present in the brief / `ranked.csv`:

- **Premium size** (`mid`) matters — prefer meaningful credits, not pennies.
- **Basis** = `strike − mid` (same as Python `breakeven` / `basis` column) — would you own shares there?
- **Annualized RoC** already in the package.
- **Ignore NLR-class** deep ITM hope puts even if premium looks large.
- If the mechanical CSP list is all negative VRP / weak premium, LOOK may be empty and IGNORE says so — that is a valid triage.

## Report shape

```
# Desk triage — YYYY-MM-DD

LOOK
- Sell 1 Put TICKER DD.MM страйк K по ~mid | basis ~B | RoC ~R | why one line

IGNORE
- ticker/reason one line each (or “all ranked — weak premium / negative VRP / …”)

сейчас on LOOK #1   — or —   Nothing urgent

Not advice. Numbers from Python brief only.
```

## Python side (minimal enrichment)

Keep one RTH ranked table. Enrich so Claude does not invent:

- `basis` column (= `strike − mid`; same value as existing `breakeven`)
- Brief markdown table includes **basis** and **RoC** next to mid / VRP / Gap

No second screener. No change to hard CSP filters (Δ 0.10–0.25, DTE 2–9, earnings). Those filters still miss some wheel-style entries; triage voice must say when the list is weak for assignment-basis trading.

## Token / Finviz rules (unchanged)

- Never ask for `FINVIZ_AUTH_TOKEN`. Never scrape Finviz from chat.
- Trust Python numbers; never invent ranks or quotes.
- Stale `fetched_at` (not today America/New_York) → say stale and stop.

## Non-goals

- Second ranked pipeline / `wheel/` snapshots
- Auto-trading or Telegram bot
- Covered-call overlay alerts
- Treating NLR as a model trade

## Success criteria

- Skill + analyst prompt describe LOOK/IGNORE triage and on-request dig-in.
- `format_brief` / `rank_rows` expose basis + RoC for triage.
- `NLR` absent from `config/watchlist.txt`.
- Tests cover brief columns; no token leakage.
- Docs/spec + implementation plan under `docs/superpowers/`.

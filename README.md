# options-desk

Options pricing and strategy analysis toolkit continued from a Claude Code session.

Python module: `xtrading/skills/options.py`  
Skill docs: `.claude/skills/options-trading/SKILL.md`  
Tests: `tests/test_options.py`

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest tests/test_options.py -v
```

## What's in here

- Black-Scholes pricing, implied vol, binomial tree, Monte Carlo
- First- and second-order Greeks
- Multi-leg strategy builder (spreads, iron condor, straddle)
- IV surface helpers and option-chain screening

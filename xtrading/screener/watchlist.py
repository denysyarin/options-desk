"""Load the wheel-eligible ticker universe from a text file."""
from __future__ import annotations

from pathlib import Path


def load_watchlist(path: str | Path) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in Path(path).read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        ticker = line.upper()
        if ticker in seen:
            continue
        seen.add(ticker)
        out.append(ticker)
    return out

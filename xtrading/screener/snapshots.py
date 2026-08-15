"""Dated on-disk snapshots for overnight RV, premarket prelayer, and RTH ranks."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from xtrading.screener.lock_widget import (
    build_lock_widget,
    earnings_from_universe,
    lock_tape_markdown,
    month_vol_from_universe,
)
from xtrading.session import ET, et_date


def _json_default(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(type(obj))


def is_today_et(meta: dict, now: datetime) -> bool:
    raw = meta.get("fetched_at")
    if not raw:
        return False
    fetched = datetime.fromisoformat(str(raw))
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=ET)
    return et_date(fetched) == et_date(now)


class SnapshotStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def day_dir(self, d: date) -> Path:
        return self.root / d.isoformat()

    def _job_dir(self, d: date, job: str) -> Path:
        path = self.day_dir(d) / job
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_overnight(
        self,
        d: date,
        *,
        universe: pd.DataFrame,
        rv: dict[str, float],
        meta: dict,
    ) -> Path:
        folder = self._job_dir(d, "overnight")
        universe.to_csv(folder / "universe.csv", index=False)
        (folder / "rv.json").write_text(json.dumps(rv, indent=2, sort_keys=True))
        (folder / "meta.json").write_text(json.dumps(meta, indent=2, default=_json_default))
        order = None
        if universe is not None and not universe.empty and "Ticker" in universe.columns:
            order = [str(t) for t in universe["Ticker"]]
        payload = build_lock_widget(
            rv,
            as_of=d,
            fetched_at=str(meta.get("fetched_at", "")),
            earnings=earnings_from_universe(universe),
            month_vol=month_vol_from_universe(universe),
            order=order,
        )
        lock_text = json.dumps(payload, indent=2) + "\n"
        (self.root / "lock-widget.json").write_text(lock_text)
        (self.root / "lock-tape.md").write_text(lock_tape_markdown(payload))
        return folder

    def write_premarket(
        self,
        d: date,
        *,
        snapshot: pd.DataFrame,
        meta: dict,
        ranked: pd.DataFrame | None = None,
        brief: str | None = None,
    ) -> Path:
        folder = self._job_dir(d, "premarket")
        snapshot.to_csv(folder / "snapshot.csv", index=False)
        if ranked is not None:
            ranked.to_csv(folder / "ranked.csv", index=False)
        if brief:
            (folder / "brief.md").write_text(brief)
        (folder / "meta.json").write_text(json.dumps(meta, indent=2, default=_json_default))
        return folder

    def write_rth(
        self,
        d: date,
        *,
        ranked: pd.DataFrame,
        brief: str,
        meta: dict,
        job: str = "rth",
    ) -> Path:
        folder = self._job_dir(d, job)
        ranked.to_csv(folder / "ranked.csv", index=False)
        (folder / "brief.md").write_text(brief)
        (folder / "meta.json").write_text(json.dumps(meta, indent=2, default=_json_default))
        return folder

    def load_premarket_snapshot(self, d: date) -> Optional[pd.DataFrame]:
        path = self.day_dir(d) / "premarket" / "snapshot.csv"
        if not path.exists():
            return None
        return pd.read_csv(path)

    def read_meta(self, d: date, job: str) -> dict:
        path = self.day_dir(d) / job / "meta.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text())

    def load_latest_rv(self, before: date) -> tuple[Optional[date], dict[str, float]]:
        for delta in range(1, 5):
            d = before - timedelta(days=delta)
            path = self.day_dir(d) / "overnight" / "rv.json"
            if path.exists():
                data = json.loads(path.read_text())
                return d, {str(k): float(v) for k, v in data.items()}
        return None, {}

"""python -m xtrading.screener overnight|premarket"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

from xtrading.data.finviz import FinvizProvider
from xtrading.screener.jobs import (
    DEFAULT_FILTERS,
    SessionSkip,
    run_overnight,
    run_premarket,
)
from xtrading.session import ET


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m xtrading.screener")
    p.add_argument("job", choices=["overnight", "premarket"])
    p.add_argument("--force", action="store_true")
    p.add_argument(
        "--snapshot-root",
        default=os.environ.get("SNAPSHOT_ROOT", "snapshots"),
    )
    args = p.parse_args(argv)
    token = os.environ.get("FINVIZ_AUTH_TOKEN")
    if not token:
        print("FINVIZ_AUTH_TOKEN is missing", file=sys.stderr)
        return 1
    filters = os.environ.get("FINVIZ_SCREENER_FILTERS", DEFAULT_FILTERS)
    cache = Path(os.environ.get("FINVIZ_CACHE", ".cache/finviz"))
    provider = FinvizProvider(token=token, cache_dir=cache)
    now = lambda: datetime.now(tz=ET)
    try:
        if args.job == "overnight":
            path = run_overnight(
                provider,
                filters=filters,
                snapshot_root=args.snapshot_root,
                now=now,
                force=args.force,
            )
        else:
            path = run_premarket(
                provider,
                filters=filters,
                snapshot_root=args.snapshot_root,
                now=now,
                force=args.force,
            )
    except SessionSkip as exc:
        print(exc)
        return 0
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

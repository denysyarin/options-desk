"""python -m xtrading.analyst --snapshot-dir snapshots/YYYY-MM-DD/rth

Reads a committed brief, asks Claude for the LOOK/IGNORE triage, pushes it to
ntfy. Every leg is optional: without an API key it pushes a headline instead,
without a topic it only writes the file. Finviz is never called here.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from xtrading.analyst.notify import build_push, claude_click_url, send_push
from xtrading.analyst.triage import (
    DEFAULT_MODEL,
    count_candidates,
    redact,
    request_triage,
)

DEFAULT_PROMPT = "prompts/daily-desk-analyst.md"
DEFAULT_NTFY_URL = "https://ntfy.sh"


def env_or(name: str, default: str) -> str:
    """Actions exports unset repo variables as empty strings, not absent keys."""
    return os.environ.get(name, "").strip() or default


def _topic_url(base: str, topic: str) -> str:
    if topic.startswith("http://") or topic.startswith("https://"):
        return topic
    return f"{base.rstrip('/')}/{topic.lstrip('/')}"


def main(argv: list[str] | None = None, *, llm_transport=None, push_transport=None) -> int:
    p = argparse.ArgumentParser(prog="python -m xtrading.analyst")
    p.add_argument("--snapshot-dir", required=True)
    p.add_argument("--out", help="write the triage markdown here")
    p.add_argument("--no-push", action="store_true")
    args = p.parse_args(argv)

    folder = Path(args.snapshot_dir)
    brief_path = folder / "brief.md"
    if not brief_path.exists():
        print(f"no brief at {brief_path}; nothing to triage")
        return 0
    brief = brief_path.read_text()
    day = folder.parent.name or folder.name

    topic = os.environ.get("NTFY_TOPIC", "").strip()
    topic_url = (
        _topic_url(env_or("NTFY_URL", DEFAULT_NTFY_URL), topic)
        if topic and not args.no_push
        else ""
    )
    click_target = env_or("DESK_CLICK", "claude")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if api_key:
        try:
            instructions = Path(env_or("ANALYST_PROMPT", DEFAULT_PROMPT)).read_text()
            triage = request_triage(
                brief=brief,
                instructions=instructions,
                api_key=api_key,
                model=env_or("ANTHROPIC_MODEL", DEFAULT_MODEL),
                transport=llm_transport,
            )
        except Exception as exc:  # best effort: the brief is already on the issue
            print(f"triage failed: {redact(str(exc))}", file=sys.stderr)
            return 1
    else:
        n = count_candidates(brief)
        triage = (
            f"# Desk triage — {day}\n\n"
            f"Brief is ready with {n} ranked put(s). No model configured "
            "(ANTHROPIC_API_KEY unset), so no LOOK/IGNORE — open the desk issue.\n"
        )

    if args.out:
        Path(args.out).write_text(triage)
        print(f"wrote {args.out}")
    else:
        print(triage)

    if not topic_url:
        return 0
    if click_target == "issue":
        click = os.environ.get("DESK_ISSUE_URL") or None
    else:
        click = claude_click_url(triage, source=f"{folder} in the options-desk repo")
    body, headers = build_push(triage, date=day, click=click)
    try:
        send_push(
            topic_url,
            body,
            headers,
            token=os.environ.get("NTFY_TOKEN") or None,
            transport=push_transport,
        )
    except Exception as exc:
        print(f"push failed: {redact(str(exc))}", file=sys.stderr)
        return 1
    print(f"pushed to {topic_url.rsplit('/', 1)[0]}/<topic>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

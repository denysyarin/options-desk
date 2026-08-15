"""Ask Claude for the short LOOK/IGNORE triage on an already-committed brief.

The model never sees Finviz credentials: the only input is `brief.md` text plus
`prompts/daily-desk-analyst.md`. Ranks stay Python's.
"""
from __future__ import annotations

import json
import re
from typing import Callable
from urllib.request import Request, urlopen

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_MAX_TOKENS = 700
TIMEOUT_S = 60

_AUTH_VALUE = re.compile(r"(auth=)[^\s&\"']+", re.IGNORECASE)

Transport = Callable[[str, bytes, dict], bytes]


def redact(text: str) -> str:
    return _AUTH_VALUE.sub(r"\1REDACTED", text)


def build_request(
    *,
    brief: str,
    instructions: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> dict:
    return {
        "model": model,
        "max_tokens": max_tokens,
        "system": instructions,
        "messages": [
            {
                "role": "user",
                "content": (
                    "Today's committed RTH brief follows. Write the triage exactly in the "
                    "template — nothing before or after it.\n\n" + redact(brief)
                ),
            }
        ],
    }


def count_candidates(brief: str) -> int:
    """Data rows in the brief's markdown table (header and separator excluded)."""
    rows = 0
    for line in brief.splitlines():
        text = line.strip()
        if not text.startswith("|") or set(text) <= set("|- "):
            continue
        if text.lower().startswith("| ticker"):
            continue
        rows += 1
    return rows


def extract_text(body: dict) -> str:
    blocks = body.get("content")
    if not isinstance(blocks, list):
        raise ValueError(f"no content in response: {json.dumps(body)[:300]}")
    parts = [b.get("text", "") for b in blocks if b.get("type") == "text"]
    text = "".join(parts).strip()
    if not text:
        raise ValueError(f"no text blocks in response: {json.dumps(body)[:300]}")
    return text


def _urlopen_transport(url: str, data: bytes, headers: dict) -> bytes:
    req = Request(url, data=data, headers=headers, method="POST")
    with urlopen(req, timeout=TIMEOUT_S) as resp:
        return resp.read()


def request_triage(
    *,
    brief: str,
    instructions: str,
    api_key: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    transport: Transport | None = None,
) -> str:
    payload = build_request(
        brief=brief, instructions=instructions, model=model, max_tokens=max_tokens
    )
    headers = {
        "content-type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": API_VERSION,
    }
    send = transport or _urlopen_transport
    raw = send(API_URL, json.dumps(payload).encode(), headers)
    return redact(extract_text(json.loads(raw.decode())))

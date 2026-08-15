"""ntfy push so the triage reaches the phone without opening GitHub."""
from __future__ import annotations

from typing import Callable
from urllib.request import Request, urlopen

NTFY_LIMIT = 4096  # bytes; longer bodies become attachments instead of text
BODY_LIMIT = 3500  # leave room for headers and multibyte tickers
TIMEOUT_S = 20
URGENT_MARKERS = ("сейчас", "urgent now")

Transport = Callable[[str, bytes, dict], bytes]


def truncate(text: str, limit: int = BODY_LIMIT) -> str:
    encoded = text.encode()
    if len(encoded) <= limit:
        return text
    return encoded[: limit - 3].decode(errors="ignore") + "…"


def build_push(triage: str, *, date: str, click: str | None) -> tuple[str, dict]:
    lowered = triage.lower()
    urgent = any(marker in lowered for marker in URGENT_MARKERS)
    headers = {
        "Title": f"Desk triage {date}",
        "Priority": "high" if urgent else "default",
        "Tags": "chart_with_upwards_trend",
        "Markdown": "yes",
    }
    if click:
        headers["Click"] = click
    return truncate(triage), headers


def _urlopen_transport(url: str, data: bytes, headers: dict) -> bytes:
    req = Request(url, data=data, headers=headers, method="POST")
    with urlopen(req, timeout=TIMEOUT_S) as resp:
        return resp.read()


def send_push(
    topic_url: str,
    body: str,
    headers: dict,
    *,
    token: str | None = None,
    transport: Transport | None = None,
) -> None:
    sent = dict(headers)
    if token:
        sent["Authorization"] = f"Bearer {token}"
    send = transport or _urlopen_transport
    send(topic_url, body.encode(), sent)

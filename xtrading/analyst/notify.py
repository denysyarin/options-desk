"""ntfy push so the triage reaches the phone without opening GitHub."""
from __future__ import annotations

from typing import Callable
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

NTFY_LIMIT = 4096  # bytes; longer bodies become attachments instead of text
BODY_LIMIT = 3500  # leave room for headers and multibyte tickers
TIMEOUT_S = 20
URGENT_MARKERS = ("act now",)  # not "urgent": the quiet line reads "Nothing urgent"
# Web Code-tab link. Works in Safari / Claude web on iPhone; no mobile-app
# requirement. The chat URL (claude.ai/new) is the wrong surface.
CLAUDE_CODE_NEW = "https://claude.ai/code/new"
DEFAULT_REPO = "denysyarin/options-desk"
PROMPT_LIMIT = 3000

Transport = Callable[[str, bytes, dict], bytes]


def truncate(text: str, limit: int = BODY_LIMIT) -> str:
    encoded = text.encode()
    if len(encoded) <= limit:
        return text
    return encoded[: limit - 3].decode(errors="ignore") + "…"


def claude_click_url(
    triage: str,
    *,
    source: str | None = None,
    repo: str = DEFAULT_REPO,
) -> str:
    """Tapping the push opens the Claude Code tab (web), not a regular chat."""
    prompt = (
        "Options desk triage below. Python already computed the ranks, so treat the "
        "numbers as given.\n\n"
        f"{triage}\n\n"
        "Using the options-trading skill: which single entry is worth taking, what is "
        "the assignment case at that basis, and what would invalidate it?"
    )
    if source:
        prompt += f"\n\nSource: {source}"
    params = {"q": truncate(prompt, PROMPT_LIMIT), "repo": repo}
    # quote (not quote_plus): Claude's q= treats "+" as a literal plus, not a space.
    return f"{CLAUDE_CODE_NEW}?{urlencode(params, quote_via=quote)}"


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

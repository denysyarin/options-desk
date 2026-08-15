"""Claude triage request/response shaping and ntfy push. No network in tests."""
import json

import pytest

from xtrading.analyst.__main__ import main
from xtrading.analyst.notify import (
    NTFY_LIMIT,
    build_push,
    send_push,
    truncate,
)
from xtrading.analyst.triage import (
    DEFAULT_MODEL,
    build_request,
    count_candidates,
    extract_text,
    redact,
    request_triage,
)

BRIEF = """# Options desk brief

As of 2026-08-17T09:30:00-04:00 (America/New_York).

| ticker | strike | DTE | mid | basis | RoC |
|---|---|---|---|---|---|
| NBIS | 205.00 | 6 | 2.10 | 202.90 | 0.622 |
"""
TRIAGE = """# Desk triage — 2026-08-17

LOOK
- Sell 1 Put NBIS 21.08 страйк 205 по ~2.10 | basis ~202.90 | RoC ~0.62

IGNORE
- rest of the table — pennies

Nothing urgent

Not advice.
"""


def test_build_request_carries_brief_instructions_and_model():
    payload = build_request(
        brief=BRIEF,
        instructions="Write LOOK / IGNORE only.",
        model="claude-sonnet-5",
        max_tokens=700,
    )
    assert payload["model"] == "claude-sonnet-5"
    assert payload["max_tokens"] == 700
    assert "LOOK" in payload["system"]
    user_text = payload["messages"][0]["content"]
    assert "NBIS" in user_text
    assert payload["messages"][0]["role"] == "user"


def test_extract_text_joins_text_blocks():
    body = {"content": [{"type": "text", "text": "# Desk"}, {"type": "text", "text": " triage"}]}
    assert extract_text(body) == "# Desk triage"


def test_extract_text_rejects_payload_without_text():
    with pytest.raises(ValueError):
        extract_text({"error": {"message": "overloaded"}})


def test_redact_strips_auth_token_shaped_values():
    dirty = "see https://elite.finviz.com/export/quote?t=SPY&auth=abc123-def secret"
    clean = redact(dirty)
    assert "abc123-def" not in clean
    assert "auth=REDACTED" in clean


def test_request_triage_sends_api_headers_and_returns_text(monkeypatch):
    monkeypatch.setenv("FINVIZ_AUTH_TOKEN", "must-never-leave")
    seen = {}

    def transport(url, data, headers):
        seen["url"] = url
        seen["data"] = data
        seen["headers"] = headers
        return json.dumps({"content": [{"type": "text", "text": TRIAGE}]}).encode()

    text = request_triage(
        brief=BRIEF,
        instructions="LOOK / IGNORE",
        api_key="sk-test",
        model="claude-sonnet-5",
        transport=transport,
    )
    assert "LOOK" in text
    assert seen["url"].endswith("/v1/messages")
    assert seen["headers"]["x-api-key"] == "sk-test"
    assert seen["headers"]["anthropic-version"]
    assert b"must-never-leave" not in seen["data"]


def test_build_push_titles_by_date_and_stays_plain_priority():
    body, headers = build_push(TRIAGE, date="2026-08-17", click="https://example.test/issues/1")
    assert "2026-08-17" in headers["Title"]
    assert "NBIS" in body
    assert headers["Priority"] == "default"
    assert headers["Click"] == "https://example.test/issues/1"
    assert headers["Markdown"] == "yes"


def test_build_push_raises_priority_when_triage_says_now():
    urgent = TRIAGE.replace("Nothing urgent", "сейчас on LOOK #1")
    _, headers = build_push(urgent, date="2026-08-17", click=None)
    assert headers["Priority"] == "high"
    assert "Click" not in headers


def test_truncate_keeps_body_inside_ntfy_limit():
    body = truncate("x" * (NTFY_LIMIT * 2))
    assert len(body.encode()) <= NTFY_LIMIT
    assert body.endswith("…")


def test_send_push_uses_bearer_only_when_token_given():
    calls = []

    def transport(url, data, headers):
        calls.append((url, data, headers))
        return b"{}"

    send_push("https://ntfy.sh/desk-abc", "hi", {"Title": "t"}, token=None, transport=transport)
    send_push("https://ntfy.sh/desk-abc", "hi", {"Title": "t"}, token="tk_1", transport=transport)
    assert "Authorization" not in calls[0][2]
    assert calls[1][2]["Authorization"] == "Bearer tk_1"
    assert calls[0][0] == "https://ntfy.sh/desk-abc"


def test_count_candidates_ignores_header_and_separator():
    assert count_candidates(BRIEF) == 1
    assert count_candidates("# brief\n\nNo surviving cash-secured puts.\n") == 0


def _snapshot(tmp_path, brief=BRIEF):
    folder = tmp_path / "2026-08-17" / "rth"
    folder.mkdir(parents=True)
    (folder / "brief.md").write_text(brief)
    return folder


def _clean_env(monkeypatch):
    for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "NTFY_TOPIC", "NTFY_URL",
                "NTFY_TOKEN", "DESK_ISSUE_URL", "ANALYST_PROMPT"):
        monkeypatch.delenv(key, raising=False)


def test_cli_writes_triage_and_pushes_it(tmp_path, monkeypatch):
    folder = _snapshot(tmp_path)
    _clean_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("NTFY_TOPIC", "desk-secret")
    pushes = []

    rc = main(
        ["--snapshot-dir", str(folder), "--out", str(tmp_path / "triage.md")],
        llm_transport=lambda url, data, headers: json.dumps(
            {"content": [{"type": "text", "text": TRIAGE}]}
        ).encode(),
        push_transport=lambda url, data, headers: pushes.append((url, data, headers)) or b"{}",
    )
    assert rc == 0
    assert "NBIS" in (tmp_path / "triage.md").read_text()
    url, data, headers = pushes[0]
    assert url == "https://ntfy.sh/desk-secret"
    assert b"NBIS" in data
    assert headers["Title"] == "Desk triage 2026-08-17"


def test_cli_without_api_key_pushes_headline_instead(tmp_path, monkeypatch):
    folder = _snapshot(tmp_path)
    _clean_env(monkeypatch)
    monkeypatch.setenv("NTFY_TOPIC", "desk-secret")
    pushes = []

    rc = main(
        ["--snapshot-dir", str(folder)],
        push_transport=lambda url, data, headers: pushes.append((url, data, headers)) or b"{}",
    )
    assert rc == 0
    assert b"1 ranked put" in pushes[0][1]
    assert b"No model configured" in pushes[0][1]


def test_cli_skips_push_when_no_topic_and_when_brief_missing(tmp_path, monkeypatch):
    folder = _snapshot(tmp_path)
    _clean_env(monkeypatch)
    pushes = []
    push = lambda url, data, headers: pushes.append(url) or b"{}"

    assert main(["--snapshot-dir", str(folder)], push_transport=push) == 0
    assert main(["--snapshot-dir", str(tmp_path / "nope")], push_transport=push) == 0
    assert pushes == []


def test_cli_treats_blank_actions_variables_as_unset(tmp_path, monkeypatch):
    """Unset repo variables arrive as "" and must not become model="" or a bare path."""
    folder = _snapshot(tmp_path)
    _clean_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_MODEL", "")
    monkeypatch.setenv("NTFY_URL", "")
    monkeypatch.setenv("NTFY_TOPIC", "desk-secret")
    sent = {}
    pushes = []

    def llm(url, data, headers):
        sent.update(json.loads(data.decode()))
        return json.dumps({"content": [{"type": "text", "text": TRIAGE}]}).encode()

    rc = main(
        ["--snapshot-dir", str(folder)],
        llm_transport=llm,
        push_transport=lambda url, data, headers: pushes.append(url) or b"{}",
    )
    assert rc == 0
    assert sent["model"] == DEFAULT_MODEL
    assert pushes == ["https://ntfy.sh/desk-secret"]


def test_cli_reports_failure_when_model_call_raises(tmp_path, monkeypatch):
    folder = _snapshot(tmp_path)
    _clean_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("NTFY_TOPIC", "desk-secret")

    def boom(url, data, headers):
        raise RuntimeError("429 overloaded")

    assert main(["--snapshot-dir", str(folder)], llm_transport=boom) == 1

"""End-of-run verdict; offline stubs only. A DONE choice is not proof."""

import json

from jevium import llm, verifier

GOALS = ["Open the search page", "Search for boots"]
PAGE = {"url": "https://shop.test/results", "title": "Results", "text": "leather boots, 42 EUR"}
HISTORY = [{"action": "Type Search", "kind": "fill", "text": "boots"}]


def test_verify_parses_strict_verdict(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    payload = json.dumps({"success": True, "reason": "results show boots"})
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: payload)
    assert verifier.verify(GOALS, PAGE, HISTORY) == {"success": True, "reason": "results show boots"}


def test_verify_rejects_wrong_types(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: json.dumps({"success": "yes", "reason": "r"}))
    out = verifier.verify(GOALS, PAGE, HISTORY)
    assert out["success"] is None and "invalid" in out["reason"]


def test_verify_failure_is_unknown(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")

    def boom(*_a, **_k):
        raise ValueError("Model returned no valid JSON object.")

    monkeypatch.setattr(llm, "chat_json", boom)
    assert verifier.verify(GOALS, PAGE, HISTORY)["success"] is None


def test_verify_skips_without_key(monkeypatch):
    monkeypatch.delenv("TEXT_MODEL_API_KEY", raising=False)
    out = verifier.verify(GOALS, PAGE, HISTORY)
    assert out["success"] is None and "TEXT_MODEL_API_KEY" in out["reason"]


def test_verify_prompt_contains_goals_and_evidence(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    seen = {}

    def spy(system, user, model=None):
        seen["system"], seen["user"] = system, user
        return json.dumps({"success": False, "reason": "x"})

    monkeypatch.setattr(llm, "chat_json", spy)
    verifier.verify(GOALS, PAGE, HISTORY)
    assert "Open the search page" in seen["user"]
    assert "https://shop.test/results" in seen["user"]
    assert "boots" in seen["user"]
    assert "untrusted" in seen["system"]


def test_verify_retries_once_on_transient_parse_failure(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    calls = []

    def flaky(*_a, **_k):
        calls.append(1)
        if len(calls) == 1:
            raise ValueError("Model returned no valid JSON object.")
        return json.dumps({"success": True, "reason": "ok on retry"})

    monkeypatch.setattr(llm, "chat_json", flaky)
    out = verifier.verify(GOALS, PAGE, HISTORY)
    assert out == {"success": True, "reason": "ok on retry"}
    assert len(calls) == 2


def test_verify_survives_provider_http_error(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")

    def boom(*_a, **_k):
        raise RuntimeError("Model provider returned HTTP 503; no action executed.")

    monkeypatch.setattr(llm, "post_json", boom)
    out = verifier.verify(GOALS, PAGE, HISTORY)
    assert out["success"] is None and "503" in out["reason"]

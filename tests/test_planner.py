"""Planner/verifier are generative helpers; offline stubs only."""

import json

import pytest

from jevium import llm, planner


def test_chat_json_requires_key(monkeypatch):
    monkeypatch.delenv("TEXT_MODEL_API_KEY", raising=False)
    with pytest.raises(ValueError, match="TEXT_MODEL_API_KEY"):
        llm.chat_json("sys", "user")


def test_chat_json_parses_strict_object(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    monkeypatch.setattr(llm, "post_json", lambda *a: {"choices": [{"message": {"content": '{"goals":["a"]}'}}]})
    assert llm.chat_json("sys", "user") == '{"goals":["a"]}'


def test_plan_includes_url_context(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    prompts = []

    def capture(_system, user, _model=None):
        prompts.append(json.loads(user))
        return json.dumps({"goals": ["Use the current site search"]})

    monkeypatch.setattr(llm, "chat_json", capture)
    goals = planner.plan("search for iphone 18", url="https://digikala.com")
    assert goals == ["Use the current site search"]
    assert prompts == [
        {"task": "search for iphone 18", "url": "https://digikala.com"}
    ]


def test_plan_validates_and_strips(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    payload = json.dumps({"goals": [" Open page ", "Click buy", "", "x"]})
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: payload)
    # An empty goal makes the list invalid -> fallback to raw task.
    assert planner.plan("task") == ["task"]


def test_plan_accepts_valid_goals(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    payload = json.dumps({"goals": [" Open page ", "Click buy", "x"]})
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: payload)
    assert planner.plan("task") == ["Open page", "Click buy", "x"]


def test_plan_retries_once_then_falls_back(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    calls = []

    def bad(*_a, **_k):
        calls.append(1)
        return "not json"

    monkeypatch.setattr(llm, "chat_json", bad)
    assert planner.plan("task") == ["task"]
    assert len(calls) == 2


def test_plan_skips_without_key(monkeypatch, capsys):
    monkeypatch.delenv("TEXT_MODEL_API_KEY", raising=False)
    assert planner.plan("task") == ["task"]
    assert "TEXT_MODEL_API_KEY" in capsys.readouterr().err


def test_plan_rejects_bad_shape(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: json.dumps({"goals": ["ok", 3]}))
    assert planner.plan("task") == ["task"]


def test_plan_survives_provider_http_error(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")

    def boom(*_a, **_k):
        raise RuntimeError("Model provider returned HTTP 503; no action executed.")

    monkeypatch.setattr(llm, "post_json", boom)
    assert planner.plan("task") == ["task"]

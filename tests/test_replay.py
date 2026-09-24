"""Replay engine contracts. Offline; a Mock browser stands in for Chromium."""

from unittest.mock import Mock

import pytest

from jevium_core import replay
from jevium_core.browser import fingerprint


def page_state(actions, url="https://x.test/step"):
    state = {"url": url, "title": "T", "text": "body", "scroll": {"y": 0},
             "actions": actions, "page_risks": []}
    state["fingerprint"] = fingerprint(state)
    return state


def test_load_steps_parses_jsonl(tmp_path):
    path = tmp_path / "steps.jsonl"
    path.write_text('{"step":1,"kind":"click"}\n\n{"step":2,"kind":"wait"}\n')
    steps = replay.load_steps(str(path))
    assert [s["step"] for s in steps] == [1, 2]


def test_load_steps_rejects_invalid_and_empty(tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{not json}\n")
    with pytest.raises(ValueError, match="invalid JSON"):
        replay.load_steps(str(bad))
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    with pytest.raises(ValueError, match="no steps"):
        replay.load_steps(str(empty))


def test_locator_for_click_and_wait():
    go = {"id": "e3", "kind": "click", "label": "Go", "role": "button",
          "value": "", "node": 20}
    actions = [go, {"id": "wait", "kind": "wait", "label": "Wait for the page to update"}]
    assert replay.locator_for(go, actions) == {
        "kind": "click", "role": "button", "name": "Go", "nth": 0}
    assert replay.locator_for(actions[1], actions) == {"kind": "wait", "ms": 100}


def test_locator_for_select_includes_option_and_node_nth():
    actions = [
        {"id": "e1", "kind": "select", "label": "Color → Red", "role": "combobox",
         "value": "red", "node": 5},
        {"id": "e2", "kind": "select", "label": "Color → Blue", "role": "combobox",
         "value": "blue", "node": 5},
        {"id": "e3", "kind": "select", "label": "Size → L", "role": "combobox",
         "value": "l", "node": 6},
        {"id": "e4", "kind": "select", "label": "Size → M", "role": "combobox",
         "value": "m", "node": 7},
    ]
    loc = replay.locator_for(actions[1], actions)
    assert loc["name"] == "Color" and loc["nth"] == 0
    assert loc["option_value"] == "blue" and loc["option_label"] == "Blue"
    # nth indexes within the same role+name group, like getByRole(...).nth(...)
    assert replay.locator_for(actions[2], actions)["nth"] == 0
    assert replay.locator_for(actions[3], actions)["nth"] == 1


def test_match_prefers_testid():
    action = {"id": "e1", "kind": "fill", "label": "Username", "role": "textbox",
              "value": "", "node": 1, "testid": "user-field"}
    step = {"step": 1, "kind": "fill",
            "locator": {"kind": "fill", "testid": "user-field",
                        "role": "textbox", "name": "Username", "nth": 0}}
    assert replay.match_action(page_state([action]), step) is action


def test_match_role_name_nth_and_legacy_choice():
    first = {"id": "e1", "kind": "fill", "label": "Email", "role": "textbox",
             "value": "", "node": 1}
    second = {"id": "e2", "kind": "fill", "label": "Email", "role": "textbox",
              "value": "", "node": 2}
    page = page_state([first, second])
    step = {"step": 2, "kind": "fill",
            "locator": {"kind": "fill", "role": "textbox", "name": "Email", "nth": 1}}
    assert replay.match_action(page, step) is second
    legacy = {"step": 3, "kind": "fill", "choice": "e2"}
    assert replay.match_action(page, legacy) is second


def test_match_select_option_by_value():
    actions = [
        {"id": "e1", "kind": "select", "label": "Color → Red", "role": "combobox",
         "value": "red", "node": 5},
        {"id": "e2", "kind": "select", "label": "Color → Blue", "role": "combobox",
         "value": "blue", "node": 5},
    ]
    step = {"step": 1, "kind": "select",
            "locator": {"kind": "select", "role": "combobox", "name": "Color",
                        "nth": 0, "option_value": "blue", "option_label": "Blue"}}
    assert replay.match_action(page_state(actions), step)["value"] == "blue"


def test_match_drift_raises_replay_drift():
    step = {"step": 4, "kind": "click", "url": "https://x.test/step",
            "locator": {"kind": "click", "role": "button", "name": "Missing", "nth": 0}}
    with pytest.raises(replay.ReplayDrift) as exc:
        replay.match_action(page_state(
            [{"id": "e3", "kind": "click", "label": "Go", "role": "button",
              "value": "", "node": 20}]), step)
    assert exc.value.index == 4
    assert "Missing" in exc.value.reason
    assert exc.value.url == "https://x.test/step"


def test_replay_executes_steps_and_rebuilds_history():
    go = {"id": "e3", "kind": "click", "label": "Go", "role": "button",
          "value": "", "node": 20}
    pages = [page_state([go], url="https://x.test/a"),
             page_state([], url="https://x.test/b")]
    browser = Mock()
    browser.observe = Mock(side_effect=pages)
    browser.act = Mock()
    steps = [{"step": 1, "kind": "click", "choice": "e3", "text": None,
              "page_changed": True,
              "locator": {"kind": "click", "role": "button", "name": "Go", "nth": 0}}]
    out = replay.replay(browser, steps)
    assert out["status"] == "done"
    browser.act.assert_called_once()
    assert browser.act.call_args.args[0] is go
    assert out["history"][-1]["url"] == "https://x.test/b"
    assert out["final_page"]["url"] == "https://x.test/b"


def test_replay_resolves_secret_from_environment(monkeypatch):
    monkeypatch.setenv("JEVIUM_PASSWORD", "not-a-real-secret")
    fill = {"id": "e1", "kind": "fill", "label": "Password", "role": "textbox",
            "value": "", "node": 1, "secret": "password"}
    page = page_state([fill])
    browser = Mock()
    browser.observe = Mock(side_effect=[page, page])
    browser.act = Mock()
    steps = [{"step": 1, "kind": "fill", "text": "***",
              "locator": {"kind": "fill", "role": "textbox", "name": "Password",
                          "nth": 0, "secret": "password"}}]
    replay.replay(browser, steps)
    assert browser.act.call_args.kwargs["text"] == "not-a-real-secret"


def test_replay_missing_secret_drifts(monkeypatch):
    monkeypatch.delenv("JEVIUM_PASSWORD", raising=False)
    fill = {"id": "e1", "kind": "fill", "label": "Password", "role": "textbox",
            "value": "", "node": 1, "secret": "password"}
    browser = Mock()
    browser.observe = Mock(return_value=page_state([fill]))
    steps = [{"step": 2, "kind": "fill", "text": "***",
              "locator": {"kind": "fill", "role": "textbox", "name": "Password",
                          "nth": 0, "secret": "password"}}]
    with pytest.raises(replay.ReplayDrift, match="not configured"):
        replay.replay(browser, steps)

"""Offline contracts for a dynamic operation/target policy. No paid APIs."""

import json
import threading
import time
from copy import deepcopy
from unittest.mock import Mock, call

import httpx
import pytest

from jevium_core import agent as loop
from jevium_core import model
from jevium_core.browser import StalePage, browser_operation, fingerprint


def page():
    state = {
        "url": "https://example.test/",
        "title": "Search",
        "text": "Search",
        "scroll": {"y": 0},
        "actions": [
            {"id": "e1", "kind": "fill", "label": "Search", "role": "textbox", "value": "", "node": 10},
            {"id": "e2", "kind": "click", "label": "Open Search", "role": "textbox", "value": "", "node": 10},
            {"id": "e3", "kind": "click", "label": "Go", "role": "button", "value": "", "node": 20},
            {"id": "wait", "kind": "wait", "label": "Wait"},
        ],
    }
    state["fingerprint"] = fingerprint(state)
    return state


def choice(ids, selected):
    return {"choice": selected, "confidence": 1.0, "probabilities": {i: float(i == selected) for i in ids}}


def decision(action="e1"):
    return {
        "choice": action,
        "operation": "TYPE_TEXT",
        "target": "1",
        "confidence": 1.0,
        "probabilities": {action: 1.0},
        "latency_ms": 10,
        "usage": {},
    }


@pytest.mark.parametrize("mutation", ["unknown", "nan", "missing", "negative", "non_max", "confidence"])
def test_invalid_choice_is_rejected(mutation):
    a = choice(["a", "b"], "a")
    if mutation == "unknown":
        a["choice"] = "invented"
    elif mutation == "nan":
        a["probabilities"]["a"] = float("nan")
    elif mutation == "missing":
        del a["probabilities"]["b"]
    elif mutation == "negative":
        a["probabilities"]["b"] = -1
    elif mutation == "non_max":
        a["choice"] = "b"
    else:
        a["confidence"] = 5
    with pytest.raises(ValueError, match="Invalid TypeSafe"):
        model.validate_choice(a, {"a", "b"})


def test_one_index_per_node_with_operation_specific_targets():
    elements, targets, controls = model.action_space(page()["actions"])
    assert len(elements) == 2
    assert elements[0]["operations"] == ["TYPE_TEXT", "CLICK"]
    assert targets["TYPE_TEXT"]["1"]["id"] == "e1"
    assert targets["CLICK"]["1"]["id"] == "e2"
    assert targets["CLICK"]["2"]["id"] == "e3"
    assert "WAIT" in controls


def test_post_json_retries_network_errors(monkeypatch):
    response = httpx.Response(200, json={"ok": True})
    post = Mock(side_effect=[httpx.ConnectError("temporary"), response])
    monkeypatch.setattr(model.CLIENT, "post", post)
    monkeypatch.setattr(model.time, "sleep", lambda _seconds: None)
    assert model.post_json("https://model.test", "test", {}) == {"ok": True}
    assert post.call_count == 2


def test_post_json_honors_retry_after_header(monkeypatch):
    limited = httpx.Response(429, headers={"Retry-After": "4"})
    success = httpx.Response(200, json={"ok": True})
    post = Mock(side_effect=[limited, success])
    sleep = Mock()
    monkeypatch.setattr(model.CLIENT, "post", post)
    monkeypatch.setattr(model.time, "sleep", sleep)
    assert model.post_json("https://model.test", "test", {}) == {"ok": True}
    assert post.call_count == 2
    assert sleep.call_args_list == [call(4.0)]


def test_loading_only_page_waits_without_model_call(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    post = Mock(side_effect=AssertionError("loading-only page must not call the model"))
    monkeypatch.setattr(model, "post_json", post)
    state = {
        "url": "https://example.test/",
        "title": "Loading",
        "text": "",
        "actions": [{"id": "wait", "kind": "wait", "label": "Wait"}],
        "fingerprint": "f1",
    }
    decision = model.choose(state, "Search for iPhone 18", [])
    assert decision["operation"] == "WAIT"
    assert decision["choice"] == "wait"
    assert decision["confidence"] == 1.0
    assert decision["human_intervention"] == 0.0
    post.assert_not_called()


def test_all_heads_are_one_request_and_only_matching_head_executes(monkeypatch):
    calls = []

    def post(_url, _key, body):
        calls.append(body)
        return {
            "model": "test",
            "answers": {
                "operation": choice(body["questions"]["operation"]["criteria"], "TYPE_TEXT"),
                "type_text_target": choice(["1"], "1"),
                "click_target": {"choice": "invented"},
            },
        }

    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", post)
    d = model.choose(page(), "Find a book", [])
    assert len(calls) == 1
    assert d["operation"] == "TYPE_TEXT" and d["target"] == "1" and d["choice"] == "e1"
    assert set(calls[0]["questions"]) == {"operation", "click_target", "type_text_target", "human_intervention"}


def test_click_cannot_consume_a_text_target(monkeypatch):
    def post(_url, _key, body):
        return {
            "model": "test",
            "answers": {
                "operation": choice(body["questions"]["operation"]["criteria"], "CLICK"),
                "type_text_target": choice(["1"], "1"),
                "click_target": choice(["1", "2", "999"], "999"),
            },
        }

    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", post)
    with pytest.raises(ValueError, match="Invalid TypeSafe"):
        model.choose(page(), "Find a book", [])


def test_target_head_receives_control_state_and_full_next_step_rules(monkeypatch):
    p = page()
    p["actions"].insert(0, {
        "id": "toggle", "kind": "click", "label": "Free cancellation", "node": 30,
        "role": "checkbox", "checked": "true", "selected": False,
    })

    def post(_url, _key, body):
        questions = body["questions"]
        target = questions["click_target"]
        assert target["criteria"]["1"]["checked"] == "true"
        assert target["criteria"]["1"]["selected"] is False
        assert questions["operation"]["instructions"]["rules"] in target["instructions"]["rules"]
        return {
            "model": "test",
            "answers": {
                "operation": choice(questions["operation"]["criteria"], "CLICK"),
                "click_target": choice(target["criteria"], "3"),
            },
        }

    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", post)
    d = model.choose(p, "Search with free cancellation", [])
    assert d["choice"] == "e3"


def test_quoted_task_text_still_uses_the_llm(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    post = Mock(return_value={"choices": [{"message": {"content": '{"text":"Zurich"}'}}]})
    monkeypatch.setattr(model, "post_json", post)
    context = model.field_context('Fly from "Zurich" to London', page()["actions"][0], page(), [])
    assert model.field_text(context)[0] == "Zurich"
    assert post.call_count == 1
    sent = json.loads(post.call_args.args[2]["messages"][1]["content"])
    assert sent["goal"] == 'Fly from "Zurich" to London'


def test_text_helper_accepts_provider_stop_token(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    monkeypatch.setattr(
        model,
        "post_json",
        Mock(return_value={"choices": [{"message": {"content": '{"text":"Zurich"}<|im_end|>'}}]}),
    )
    assert model.field_text({"goal": 'Enter "Zurich"'})[0] == "Zurich"


def test_missing_text_credential_stops_before_guessing(monkeypatch):
    monkeypatch.delenv("TEXT_MODEL_API_KEY", raising=False)
    with pytest.raises(ValueError, match="TEXT_MODEL_API_KEY"):
        model.field_text({"goal": 'Enter "Zurich"'})


@pytest.fixture
def runner():
    a = loop.Agent.__new__(loop.Agent)
    a.screenshots = False
    a.pending_text = None
    a._resume = threading.Event()
    a.max_steps = loop.MAX_STEPS
    p = page()
    a.state = {
        "browser": Mock(fresh=Mock(return_value=True), observe=Mock(return_value=p)),
        "page": p,
        "decision": decision(),
        "goal": "Find a book",
        "history": [],
        "decisions": [],
        "status": "predicted",
        "started_at": time.perf_counter(),
        "record": False,
        "text_calls": [],
        "waiting": None,
        "last_pause": None,
        "login_submitted_fingerprint": None,
        "elapsed_ms": 0,
        "plan": ["Find a book"],
        "plan_index": 0,
    }
    return a


def test_stale_decision_is_consumed_before_any_mutation(runner):
    runner.state["browser"].fresh.return_value = False
    with pytest.raises(StalePage):
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    runner.state["browser"].act.assert_not_called()
    assert runner.state["decision"] is None


def test_generated_text_reused_only_for_identical_retry_context(runner, monkeypatch):
    helper = Mock(return_value=("book", {"model": "test", "latency_ms": 10}))
    monkeypatch.setattr(loop, "field_text", helper)
    runner.state["browser"].act.side_effect = [StalePage("Changed before input"), None]
    with pytest.raises(StalePage):
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    runner.state["decision"] = decision()
    runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert helper.call_count == 1
    assert runner.state["browser"].act.call_count == 2  # The first call rejects before any browser input.
    assert runner.pending_text is None


def test_changed_field_context_does_not_reuse_generated_text(runner, monkeypatch):
    helper = Mock(return_value=("book", {"model": "test", "latency_ms": 10}))
    monkeypatch.setattr(loop, "field_text", helper)
    runner.state["browser"].act.side_effect = [StalePage("Changed before input"), None]
    with pytest.raises(StalePage):
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    runner.state["page"]["text"] = "Different page context"
    runner.state["decision"] = decision()
    runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert helper.call_count == 2


def test_loading_waits_do_not_trigger_no_progress_stop(runner):
    for _ in range(5):
        runner.state["decision"] = decision("wait")
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert len(runner.state["history"]) == 5 and runner.state["status"] == "ready"


def test_stale_observation_preserves_executed_action(runner):
    runner.state["decision"] = decision("e3")
    runner.state["browser"].observe.side_effect = StalePage("changed")
    with pytest.raises(StalePage):
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert runner.state["history"][-1]["action"] == "Go"
    runner.state["browser"].act.assert_called_once()


def test_observation_is_one_atomic_browser_read(monkeypatch):
    import jevium_core.browser as browser

    p = page()
    cdp = Mock(return_value={"result": {"value": p}})
    monkeypatch.setattr(browser, "cdp", cdp)
    actual = browser_operation({"operation": "observe", "session": "test", "screenshot": False})
    assert actual["actions"] == p["actions"]
    assert cdp.call_count == 1
    assert cdp.call_args.args[0] == "Runtime.evaluate"


def test_executor_rejects_a_stale_page_before_browser_input(monkeypatch):
    import jevium_core.browser as browser

    b = browser.Browser.__new__(browser.Browser)
    b.fresh = Mock(return_value=False)
    operation = Mock()
    monkeypatch.setattr(browser, "browser_operation", operation)
    with pytest.raises(StalePage):
        b.act(page()["actions"][0], page(), "book")
    operation.assert_not_called()


@pytest.mark.parametrize("response", [{"exceptionDetails": {}}, {"result": {}}])
def test_interrupted_dropdown_mutation_cannot_be_retried_as_stale(monkeypatch, response):
    import jevium_core.browser as browser

    # A navigation can destroy the evaluation result after the change event already fired.
    if "exceptionDetails" in response:
        response["exceptionDetails"] = {"text": "Execution context destroyed"}
    cdp = Mock(return_value=response)
    monkeypatch.setattr(browser, "cdp", cdp)
    with pytest.raises(RuntimeError, match="Dropdown execution"):
        browser_operation({"operation": "act", "session": "test", "action": {
            "id": "e1", "kind": "select", "node": 1, "value": "Design",
        }})
    assert cdp.call_count == 1


def test_fingerprint_tracks_values_and_identity_not_screenshots():
    p = page()
    other = deepcopy(p)
    other["screenshot"] = "changed"
    assert fingerprint(p) == fingerprint(other)
    other["actions"][0]["node"] = 99
    assert fingerprint(p) != fingerprint(other)


@pytest.mark.parametrize(
    "content", ["Thinking: Zurich", '{"text":null}', '{"text":"Zurich","extra":true}', '{"text":123}']
)
def test_text_helper_rejects_invalid_values(monkeypatch, content):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", Mock(return_value={"choices": [{"message": {"content": content}}]}))
    with pytest.raises(ValueError, match="nothing typed"):
        model.field_text({"goal": "Find a flight"})


def test_navigation_during_prediction_reobserves_without_action(runner):
    runner.state["browser"].fresh.side_effect = StalePage("Document navigating")
    runner.command("tick")
    assert runner.state["status"] == "ready"
    assert runner.state["decision"] is None
    runner.state["browser"].act.assert_not_called()

def test_browser_operation_uses_injected_call():
    import jevium_core.browser as browser

    seen = []

    def fake(method, **params):
        seen.append(method)
        return {
            "result": {
                "value": {
                    "url": "https://injected.test/", "title": "T", "text": "hi",
                    "scroll": {"y": 0}, "actions": [], "marker": "m",
                    "page_key": [1], "guards": {},
                }
            }
        }

    out = browser.browser_operation({"operation": "observe", "screenshot": False}, cdp_call=fake)
    assert out["url"] == "https://injected.test/"
    assert "fingerprint" in out
    assert seen == ["Runtime.evaluate"]

def test_base_browser_evaluate_uses_its_call():
    from jevium_core.browser import BaseBrowser

    class B(BaseBrowser):
        def call(self, method, **params):
            assert method == "Runtime.evaluate"
            return {"result": {"value": 42}}

    assert B().evaluate("1+1") == 42


def test_base_browser_evaluate_raises_stale_on_exception():
    from jevium_core.browser import BaseBrowser

    class B(BaseBrowser):
        def call(self, method, **params):
            return {"exceptionDetails": {"text": "gone"}}

    with pytest.raises(StalePage):
        B().evaluate("x")

def risky_page():
    p = page()
    p["actions"][0]["risk"] = "otp"   # fill: Search
    p["actions"][1]["risk"] = "otp"   # click: Open Search — same node; snapshot tags base once
    p["actions"][2]["risk"] = "pay"   # click: Go
    p["page_risks"] = ["captcha"]
    p["fingerprint"] = fingerprint(p)
    return p


def login_page(*, username="", password="", submit=True, captcha=False):
    actions = [
        {"id": "u1", "kind": "fill", "label": "Username", "role": "textbox",
         "value": username, "node": 10, "secret": "username", "risk": "username", "login_form": True},
        {"id": "u1c", "kind": "click", "label": "Open Username", "role": "textbox",
         "value": username, "node": 10, "secret": "username", "risk": "username", "login_form": True},
        {"id": "p1", "kind": "fill", "label": "Password", "role": "textbox",
         "value": password, "node": 11, "secret": "password", "risk": "credential", "login_form": True},
        {"id": "p1c", "kind": "click", "label": "Open Password", "role": "textbox",
         "value": password, "node": 11, "secret": "password", "risk": "credential", "login_form": True},
    ]
    if submit:
        actions.append({"id": "s1", "kind": "click", "label": "Sign in", "role": "button",
                        "value": "", "node": 20, "login_form": True})
    state = {
        "url": "https://example.test/login", "title": "Login", "text": "Sign in",
        "scroll": {"y": 0}, "actions": actions,
        "page_risks": ["captcha"] if captcha else [],
    }
    state["fingerprint"] = fingerprint(state)
    return state


def test_empty_configured_secret_maps_to_type_secret(monkeypatch):
    monkeypatch.setenv("JEVIUM_USERNAME", "alice@example.test")
    monkeypatch.setenv("JEVIUM_PASSWORD", "not-a-real-secret")
    elements, targets, _controls = model.action_space(login_page()["actions"])
    assert "TYPE_SECRET" in targets
    assert set(targets["TYPE_SECRET"]) == {"1", "2"}
    assert targets["TYPE_SECRET"]["1"]["id"] == "u1"
    username = next(e for e in elements if e["label"] == "Username")
    assert "TYPE_SECRET" in username["operations"]


def test_filled_secret_offers_no_fill_operation(monkeypatch):
    monkeypatch.setenv("JEVIUM_PASSWORD", "not-a-real-secret")
    elements, targets, _controls = model.action_space(login_page(password="***")["actions"])
    password = next(e for e in elements if e["label"] == "Password")
    assert password["value"] == "***"
    assert password["operations"] == ["CLICK"]
    assert "TYPE_SECRET" not in targets
    assert all(a["id"] != "p1" for group in targets.values() for a in group.values())


def test_unconfigured_required_secret_stays_type_text(monkeypatch):
    monkeypatch.delenv("JEVIUM_PASSWORD", raising=False)
    monkeypatch.delenv("JEVIUM_USERNAME", raising=False)
    _elements, targets, _controls = model.action_space(login_page()["actions"])
    assert "TYPE_SECRET" not in targets
    assert targets["TYPE_TEXT"]["1"]["id"] == "u1"          # optional username: LLM path
    assert targets["TYPE_TEXT"]["2"]["id"] == "p1"          # required password: gated TYPE_TEXT
    # A filled secret also offers no fill operation, even with nothing configured.
    _elements2, targets2, _controls2 = model.action_space(login_page(password="***")["actions"])
    assert all(a["id"] != "p1" for group in targets2.values() for a in group.values())


def test_action_space_surfaces_human_risk():
    elements, _targets, _controls = model.action_space(risky_page()["actions"])
    assert elements[0]["human_risk"] == "otp"
    assert elements[1]["human_risk"] == "pay"


def test_choose_sends_page_risks_and_risk_criteria(monkeypatch):
    captured = {}

    def post(_url, _key, body):
        captured.update(body)
        return {
            "model": "test",
            "answers": {
                "operation": choice(body["questions"]["operation"]["criteria"], "CLICK"),
                "click_target": choice(list(body["questions"]["click_target"]["criteria"]), "2"),
            },
        }

    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", post)
    d = model.choose(risky_page(), "Pay for the order", [])
    assert captured["state"]["page"]["page_risks"] == ["captcha"]
    assert captured["questions"]["click_target"]["criteria"]["1"]["human_risk"] == "otp"
    assert d["target_risk"] == "pay"


def test_choose_target_risk_is_none_without_risk(monkeypatch):
    def post(_url, _key, body):
        return {
            "model": "test",
            "answers": {
                "operation": choice(body["questions"]["operation"]["criteria"], "TYPE_TEXT"),
                "type_text_target": choice(["1"], "1"),
            },
        }

    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", post)
    assert model.choose(page(), "Find a book", [])["target_risk"] is None

def test_needs_human_is_offered_as_structured_criteria(monkeypatch):
    captured = {}

    def post(_url, _key, body):
        captured.update(body)
        return {
            "model": "test",
            "answers": {
                "operation": choice(body["questions"]["operation"]["criteria"], "NEEDS_HUMAN"),
            },
        }

    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", post)
    d = model.choose(page(), "Checkout the cart", [])
    assert d["choice"] == "NEEDS_HUMAN" and d["operation"] == "NEEDS_HUMAN"
    crit = captured["questions"]["operation"]["criteria"]["NEEDS_HUMAN"]
    assert isinstance(crit, dict) and {"what", "not_for", "examples"} <= set(crit)


def test_human_intervention_noul_is_parsed_when_present(monkeypatch):
    def post(_url, _key, body):
        assert body["questions"]["human_intervention"]["type"] == "noul"
        click_ids = list(body["questions"]["click_target"]["criteria"])
        return {
            "model": "test",
            "answers": {
                "operation": choice(body["questions"]["operation"]["criteria"], "CLICK"),
                "click_target": choice(click_ids, "2"),
                "human_intervention": {"type": "noul", "noul": 0.82},
            },
        }

    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", post)
    assert model.choose(page(), "Checkout", [])["human_intervention"] == 0.82


@pytest.mark.parametrize("human_answer", [
    None,
    {"type": "noul"},
    {"type": "noul", "noul": "high"},
    {"type": "noul", "noul": 7},
])
def test_malformed_noul_is_ignored_not_fatal(monkeypatch, human_answer):
    def post(_url, _key, body):
        ids = list(body["questions"]["operation"]["criteria"])
        op = "CLICK" if "CLICK" in ids else ids[0]
        answers = {"operation": choice(ids, op)}
        if op in {"CLICK", "TYPE_TEXT", "SELECT"}:
            target_key = {"CLICK": "click_target", "TYPE_TEXT": "type_text_target",
                          "SELECT": "select_target"}[op]
            answers[target_key] = choice(list(body["questions"][target_key]["criteria"]), "1")
        if human_answer is not None:
            answers["human_intervention"] = human_answer
        return {"model": "test", "answers": answers}

    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", post)
    assert model.choose(page(), "Checkout", [])["human_intervention"] is None

def gated_decision(*, confidence=1.0, operation="CLICK", action="e3", human=None, risk=None):
    d = decision(action)
    d.update(operation=operation, confidence=confidence,
             human_intervention=human, target_risk=risk, target=None)
    return d


def test_confidence_gate_pauses_predict(runner, monkeypatch):
    monkeypatch.setenv("JEVIUM_MIN_CONFIDENCE", "0.3")
    monkeypatch.setattr(loop, "choose", lambda *_a, **_k: gated_decision(confidence=0.1))
    runner.state["status"] = "ready"
    runner.state["decision"] = None
    runner.command("predict", {})
    assert runner.state["status"] == "waiting_human"
    assert runner.state["waiting"]["trigger"] == "confidence"
    assert runner.state["decision"] is None


def test_noul_gate_pauses_predict(runner, monkeypatch):
    monkeypatch.setenv("JEVIUM_MIN_CONFIDENCE", "0")
    monkeypatch.setattr(loop, "choose", lambda *_a, **_k: gated_decision(human=0.9))
    runner.state["status"] = "ready"
    runner.state["decision"] = None
    runner.command("predict", {})
    assert runner.state["waiting"]["trigger"] == "page"


def test_pay_gate_pauses_predict(runner, monkeypatch):
    monkeypatch.setenv("JEVIUM_MIN_CONFIDENCE", "0")
    monkeypatch.setattr(loop, "choose", lambda *_a, **_k: gated_decision(risk="pay"))
    runner.state["status"] = "ready"
    runner.state["decision"] = None
    runner.command("predict", {})
    assert runner.state["waiting"]["trigger"] == "pay"
    assert runner.state["waiting"]["element"]["label"] == "Go"
    assert "Element: Go." in runner.state["waiting"]["reason"]


def test_captcha_gate_pauses_before_configured_fill(runner, monkeypatch):
    monkeypatch.setenv("JEVIUM_USERNAME", "alice@example.test")
    monkeypatch.setenv("JEVIUM_PASSWORD", "not-a-real-secret")
    monkeypatch.setattr(model, "post_json", Mock(side_effect=AssertionError("must not call model")))
    runner.state["page"] = login_page(captcha=True)
    runner.state["status"] = "ready"
    runner.state["decision"] = None
    runner.command("predict", {})
    assert runner.state["status"] == "waiting_human"
    assert runner.state["waiting"]["trigger"] == "captcha"
    assert runner.state["waiting"]["element"]["label"] == "CAPTCHA challenge"
    assert runner.state["decision"] is None
    runner.state["browser"].act.assert_not_called()


def test_missing_secret_gate_pauses_at_password(runner, monkeypatch):
    monkeypatch.delenv("JEVIUM_PASSWORD", raising=False)
    monkeypatch.setenv("JEVIUM_MIN_CONFIDENCE", "0")
    monkeypatch.setattr(
        loop, "choose",
        lambda *_a, **_k: gated_decision(operation="TYPE_TEXT", action="p1", risk="credential"),
    )
    runner.state["page"] = login_page()
    runner.state["status"] = "ready"
    runner.state["decision"] = None
    runner.command("predict", {})
    assert runner.state["waiting"]["trigger"] == "secret"
    assert runner.state["waiting"]["element"]["label"] == "Password"
    assert "Element: Password." in runner.state["waiting"]["reason"]


def test_otp_gate_carries_element_label(runner, monkeypatch):
    monkeypatch.setenv("JEVIUM_MIN_CONFIDENCE", "0")
    monkeypatch.setattr(
        loop, "choose",
        lambda *_a, **_k: gated_decision(operation="TYPE_TEXT", action="e1", risk="otp"),
    )
    runner.state["status"] = "ready"
    runner.state["decision"] = None
    runner.command("predict", {})
    assert runner.state["waiting"]["trigger"] == "otp"
    assert runner.state["waiting"]["element"]["label"] == "Search"
    assert "Element: Search." in runner.state["waiting"]["reason"]


def test_pay_gate_wins_over_low_confidence(runner, monkeypatch):
    monkeypatch.setenv("JEVIUM_MIN_CONFIDENCE", "0.3")
    monkeypatch.setattr(
        loop, "choose",
        lambda *_a, **_k: gated_decision(confidence=0.1, risk="pay"),
    )
    runner.state["status"] = "ready"
    runner.state["decision"] = None
    runner.command("predict", {})
    assert runner.state["waiting"]["trigger"] == "pay"


def test_missing_card_configuration_pauses_at_card_field(runner, monkeypatch):
    monkeypatch.delenv("JEVIUM_CARD_NUMBER", raising=False)
    monkeypatch.setenv("JEVIUM_MIN_CONFIDENCE", "0")
    card_page = {
        "url": "https://example.test/pay", "title": "Pay", "text": "Card number",
        "scroll": {"y": 0},
        "actions": [
            {"id": "c1", "kind": "fill", "label": "Card number", "role": "textbox",
             "value": "", "node": 30, "secret": "card_number", "risk": "card_number"},
        ],
        "page_risks": [],
    }
    card_page["fingerprint"] = fingerprint(card_page)
    monkeypatch.setattr(
        loop, "choose",
        lambda *_a, **_k: gated_decision(operation="TYPE_TEXT", action="c1", risk="card_number"),
    )
    runner.state["page"] = card_page
    runner.state["status"] = "ready"
    runner.state["decision"] = None
    runner.command("predict", {})
    assert runner.state["waiting"]["trigger"] == "secret"
    assert runner.state["waiting"]["element"]["label"] == "Card number"


def test_identical_gate_overrides_once_then_pauses_again(runner, monkeypatch):
    monkeypatch.setenv("JEVIUM_MIN_CONFIDENCE", "0.3")
    monkeypatch.setattr(loop, "choose", lambda *_a, **_k: gated_decision(confidence=0.1))
    runner.state["status"] = "ready"
    runner.state["decision"] = None
    runner.command("predict", {})
    assert runner.state["status"] == "waiting_human"
    runner.state["status"] = "ready"
    runner.state["decision"] = None
    runner.command("predict", {})
    assert runner.state["status"] == "predicted"      # override consumed
    assert runner.state["last_pause"] is None
    runner.state["status"] = "ready"
    runner.state["decision"] = None
    runner.command("predict", {})
    assert runner.state["status"] == "waiting_human"  # pauses again without another resume


def test_model_trigger_never_overrides(runner, monkeypatch):
    monkeypatch.setattr(
        loop, "choose",
        lambda *_a, **_k: gated_decision(operation="NEEDS_HUMAN", action="NEEDS_HUMAN"),
    )
    runner.state["status"] = "ready"
    runner.state["decision"] = None
    runner.command("predict", {})
    runner.state["status"] = "ready"
    runner.state["decision"] = None
    runner.command("predict", {})
    assert runner.state["status"] == "waiting_human"
    assert runner.state["waiting"]["trigger"] == "model"


def test_tick_skips_act_while_waiting(runner, monkeypatch):
    monkeypatch.setenv("JEVIUM_MIN_CONFIDENCE", "0.3")
    monkeypatch.setattr(loop, "choose", lambda *_a, **_k: gated_decision(confidence=0.1))
    runner.state["status"] = "ready"
    runner.state["decision"] = None
    runner.command("tick")
    assert runner.state["status"] == "waiting_human"
    runner.state["browser"].act.assert_not_called()


def test_run_pauses_with_callback_then_finishes(runner, monkeypatch):
    monkeypatch.setenv("JEVIUM_MIN_CONFIDENCE", "0.3")
    low = gated_decision(confidence=0.1)
    done = decision("DONE")
    done.update(operation="DONE", target=None, human_intervention=None, target_risk=None)
    answers = iter([low, done])
    monkeypatch.setattr(loop, "choose", lambda *_a, **_k: next(answers))
    runner.state["status"] = "ready"
    runner.state["decision"] = None
    seen = []

    def on_waiting(w):
        seen.append(w["trigger"])
        runner.resume()

    states = list(runner.run(on_waiting=on_waiting))
    assert seen == ["confidence"]
    assert states[-1]["status"] == "done"


def test_after_resume_reobserves_and_clears_waiting(runner):
    runner.state["status"] = "waiting_human"
    runner.state["waiting"] = {"trigger": "pay", "reason": "r", "fingerprint": "f"}
    runner._resume.set()
    runner._after_resume()
    assert runner.state["status"] == "ready"
    assert runner.state["waiting"] is None
    assert runner.state["browser"].observe.called
    assert not runner._resume.is_set()


def test_needs_human_choice_in_act_pauses_not_crashes(runner):
    # Defense in depth: the gate normally pre-empts this path; act must not StopIteration.
    runner.state["decision"] = {**decision("NEEDS_HUMAN"), "operation": "NEEDS_HUMAN"}
    out = runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert out["status"] == "waiting_human"
    runner.state["browser"].act.assert_not_called()


def test_max_steps_attribute_bounds_history(runner):
    runner.max_steps = 2
    for _ in range(2):
        runner.state["decision"] = decision("wait")
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    with pytest.raises(ValueError, match="budget"):
        runner.state["decision"] = decision("wait")
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})


@pytest.mark.parametrize("floor_value", ["", "abc", "0.3", "0"])
def test_confidence_floor_env_never_crashes(runner, monkeypatch, floor_value):
    monkeypatch.setenv("JEVIUM_MIN_CONFIDENCE", floor_value)
    monkeypatch.setattr(loop, "choose", lambda *_a, **_k: gated_decision(confidence=0.1))
    runner.state["status"] = "ready"
    runner.state["decision"] = None
    runner.command("predict", {})
    if floor_value == "0":
        assert runner.state["status"] == "predicted"   # disabled: decision passes
    else:
        # "" and "abc" fall back to the default 0.3; 0.3 with confidence 0.1 pauses
        assert runner.state["status"] == "waiting_human"


def test_record_writes_steps_jsonl(runner, tmp_path):
    import base64 as b64

    runner.record_dir = tmp_path
    runner.state["record"] = True
    runner.state["page"]["screenshot"] = b64.b64encode(b"jpeg").decode()
    runner.state["decision"] = decision("wait")
    runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    lines = (tmp_path / "steps.jsonl").read_text().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["kind"] == "wait" and entry["choice"] == "wait"


def test_configured_secret_fill_skips_model(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setenv("JEVIUM_USERNAME", "alice@example.test")
    monkeypatch.setenv("JEVIUM_PASSWORD", "not-a-real-secret")
    monkeypatch.setattr(model, "post_json", Mock(side_effect=AssertionError("must not call model")))
    d = model.choose(login_page(), "Log in", [])
    assert d["model"] == "configured-fallback"
    assert d["operation"] == "TYPE_SECRET"
    assert d["choice"] == "u1"
    assert d["target"] == "1"
    assert d["target_risk"] == "username"
    assert d["request"] == {}


def test_configured_fill_targets_next_empty_secret(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setenv("JEVIUM_USERNAME", "alice@example.test")
    monkeypatch.setenv("JEVIUM_PASSWORD", "not-a-real-secret")
    monkeypatch.setattr(model, "post_json", Mock(side_effect=AssertionError("must not call model")))
    d = model.choose(login_page(username="***"), "Log in", [])
    assert d["choice"] == "p1"
    assert d["target"] == "2"


def test_configured_card_fill_skips_model(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setenv("JEVIUM_CARD_NUMBER", "4111111111111111")
    page_state = {
        "url": "https://example.test/pay", "title": "Pay", "text": "Card number",
        "scroll": {"y": 0},
        "actions": [
            {"id": "c1", "kind": "fill", "label": "Card number", "role": "textbox",
             "value": "", "node": 30, "secret": "card_number", "risk": "card_number"},
            {"id": "c1c", "kind": "click", "label": "Open Card number", "role": "textbox",
             "value": "", "node": 30, "secret": "card_number", "risk": "card_number"},
        ],
        "page_risks": [],
    }
    page_state["fingerprint"] = fingerprint(page_state)
    monkeypatch.setattr(model, "post_json", Mock(side_effect=AssertionError("must not call model")))
    d = model.choose(page_state, "Pay with the configured card", [])
    assert d["model"] == "configured-fallback"
    assert d["operation"] == "TYPE_SECRET"
    assert d["choice"] == "c1"
    assert d["target_risk"] == "card_number"


def test_login_submit_fallback_when_fields_filled(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", Mock(side_effect=AssertionError("must not call model")))
    d = model.choose(login_page(username="***", password="***"), "Log in", [])
    assert d["model"] == "login-fallback"
    assert d["operation"] == "CLICK"
    assert d["choice"] == "s1"
    assert d["target"] == "3"
    assert d["request"] == {}


def test_login_submit_blocked_by_empty_login_input(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test")

    def post(_url, _key, body):
        return {"model": "test", "answers": {
            "operation": choice(body["questions"]["operation"]["criteria"], "DONE")}}

    monkeypatch.setattr(model, "post_json", post)
    d = model.choose(login_page(username="", password="***"), "Log in", [])
    assert d["model"] == "test"


def test_login_submit_disabled_for_same_fingerprint(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test")

    def post(_url, _key, body):
        return {"model": "test", "answers": {
            "operation": choice(body["questions"]["operation"]["criteria"], "DONE")}}

    monkeypatch.setattr(model, "post_json", post)
    d = model.choose(login_page(username="***", password="***"), "Log in", [],
                     allow_login_submit=False)
    assert d["model"] == "test"


def test_model_payload_lists_configured_secrets_and_updated_prompts(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setenv("JEVIUM_PASSWORD", "not-a-real-secret")
    captured = {}

    def post(_url, _key, body):
        captured.update(body)
        return {"model": "test", "answers": {
            "operation": choice(body["questions"]["operation"]["criteria"], "DONE")}}

    monkeypatch.setattr(model, "post_json", post)
    # Filled password + no submit button: no fallback fires, so the network is reached.
    model.choose(login_page(username="***", password="***", submit=False), "Log in", [])
    assert captured["state"]["page"]["configured_secrets"] == ["password"]
    assert "not-a-real-secret" not in json.dumps(captured)
    assert "configured_secrets" in captured["questions"]["operation"]["instructions"]["rules"]
    assert "configured_secrets" in captured["questions"]["human_intervention"]["instructions"]
    assert "empty login/payment-secret field" in captured["questions"]["operation"]["instructions"]["rules"]


def test_configured_secret_act_types_environment_value(runner, monkeypatch):
    monkeypatch.setenv("JEVIUM_PASSWORD", "not-a-real-secret")
    helper = Mock(side_effect=AssertionError("TYPE_SECRET must not call the text helper"))
    monkeypatch.setattr(loop, "field_text", helper)
    runner.state["page"] = login_page()
    runner.state["decision"] = {
        **decision("p1"),
        "operation": "TYPE_SECRET",
        "target": "2",
        "target_risk": "credential",
        "model": "configured-fallback",
    }
    runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    helper.assert_not_called()
    assert runner.state["browser"].act.call_count == 1
    assert runner.state["browser"].act.call_args.kwargs["text"] == "not-a-real-secret"
    assert runner.state["text_calls"] == []
    entry = runner.state["history"][-1]
    assert entry["text"] == "***"
    assert entry["text_helper"] == "environment"
    dumped = json.dumps(runner.state["history"]) + json.dumps(runner.state["text_calls"])
    assert "not-a-real-secret" not in dumped


def test_act_backstop_pauses_without_configured_secret(runner, monkeypatch):
    monkeypatch.delenv("JEVIUM_PASSWORD", raising=False)
    helper = Mock(side_effect=AssertionError("must not guess a required secret"))
    monkeypatch.setattr(loop, "field_text", helper)
    runner.state["page"] = login_page()
    runner.state["decision"] = decision("p1")
    out = runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    helper.assert_not_called()
    runner.state["browser"].act.assert_not_called()
    assert out["status"] == "waiting_human"
    assert out["waiting"]["trigger"] == "secret"
    assert out["waiting"]["element"]["label"] == "Password"


def test_login_fallback_click_records_fingerprint(runner):
    runner.state["page"] = login_page(username="***", password="***")
    before = runner.state["page"]["fingerprint"]
    runner.state["decision"] = {
        **decision("s1"),
        "operation": "CLICK",
        "target": "3",
        "target_risk": None,
        "model": "login-fallback",
    }
    runner.command("act", {"fingerprint": before})
    assert runner.state["login_submitted_fingerprint"] == before
    assert runner.state["history"][-1]["action"] == "Sign in"


def test_predict_disables_login_submit_for_same_fingerprint(runner, monkeypatch):
    runner.state["page"] = login_page(username="***", password="***")
    runner.state["login_submitted_fingerprint"] = runner.state["page"]["fingerprint"]
    seen = {}

    def fake_choose(_page, _goal, _history, **kwargs):
        seen.update(kwargs)
        return gated_decision(confidence=1.0)

    monkeypatch.setattr(loop, "choose", fake_choose)
    runner.state["status"] = "ready"
    runner.state["decision"] = None
    runner.command("predict", {})
    assert seen["allow_login_submit"] is False


def test_resume_settle_failure_yields_waiting_state(runner, monkeypatch):
    monkeypatch.setattr(loop.time, "sleep", lambda _s: None)
    runner.state["status"] = "waiting_human"
    runner.state["waiting"] = {"trigger": "pay", "reason": "r", "fingerprint": "f", "element": None}
    runner.state["browser"].observe.side_effect = StalePage("never settles")
    prompts = []

    def on_waiting(_waiting):
        prompts.append(1)
        if len(prompts) == 1:
            runner.resume()
        else:
            # Old run() loops back into on_waiting instead of yielding; fail fast, never hang.
            raise RuntimeError("run() must yield the waiting snapshot after a failed re-observe")

    gen = runner.run(on_waiting=on_waiting)
    state = next(gen)
    gen.close()
    assert state["status"] == "waiting_human"
    assert state["waiting"]["reason"] == (
        "Page did not settle after resume. Check the browser, then try again."
    )

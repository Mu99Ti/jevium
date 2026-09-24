"""TypeSafe makes choices; an optional small OpenAI-compatible model writes field values."""

import json
import math
import os
import re
import time

import httpx

from .questions import HUMAN_INTERVENTION, NEXT_ACTION, TARGET, TEXT_VALUE

CLIENT = httpx.Client(http2=True, timeout=25)

SENSITIVE_ENV = {
    "username": "JEVIUM_USERNAME",
    "password": "JEVIUM_PASSWORD",
    "card_number": "JEVIUM_CARD_NUMBER",
    "card_expiry": "JEVIUM_CARD_EXPIRY",
    "card_cvv": "JEVIUM_CARD_CVV",
    "card_name": "JEVIUM_CARD_NAME",
}
REQUIRED_SECRETS = frozenset({"password", "card_number", "card_expiry", "card_cvv", "card_name"})
SECRET_ORDER = {kind: i for i, kind in enumerate(
    ("username", "password", "card_name", "card_number", "card_expiry", "card_cvv")
)}


def configured_secret(kind):
    return os.environ.get(SENSITIVE_ENV.get(kind, ""), "")


def task_contains_configured_secret(task):
    return any(
        value and value in task
        for value in (configured_secret(kind) for kind in REQUIRED_SECRETS)
    )


_CREDENTIAL_PAIR_PATTERNS = (
    # username password <user> <pass>
    re.compile(r"\busername\s+password\s+(\S+)\s+(\S+)", re.I),
    # username[:=] <user> password[:=] <pass>
    re.compile(r"\busername\s*[:=]?\s*(\S+)\s+password\s*[:=]?\s*(\S+)", re.I),
    # password[:=] <pass> username[:=] <user>
    re.compile(r"\bpassword\s*[:=]?\s*(\S+)\s+username\s*[:=]?\s*(\S+)", re.I),
)
_TASK_CREDENTIAL_HINT = re.compile(
    r"\busername\b.*\bpassword\b|\bpassword\b.*\busername\b", re.I | re.S)
_TASK_LOGIN_HINT = re.compile(
    r"\b(login|sign\s?in|signin|log\s?on|logon|authenticate|authentication)\b", re.I)


def extract_task_credentials(task):
    """Split a structured username/password pair out of a task.

    Returns (clean_task, username, password). Extraction requires both field
    names, a login intent, and a password-shaped value (>=6 chars with a digit
    and a symbol); otherwise the task is returned untouched so the existing
    reject/pause paths still apply. The password never remains in clean_task;
    the username is kept there as harmless context for fallback typing.
    """
    if not (_TASK_CREDENTIAL_HINT.search(task) and _TASK_LOGIN_HINT.search(task)):
        return task, None, None
    for index, pattern in enumerate(_CREDENTIAL_PAIR_PATTERNS):
        match = pattern.search(task)
        if not match:
            continue
        if index == 2:
            password, username = match.group(1), match.group(2)
        else:
            username, password = match.group(1), match.group(2)
        if not (len(username) >= 2 and len(password) >= 6
                and re.search(r"\d", password) and re.search(r"[^A-Za-z0-9]", password)):
            return task, None, None
        clean = pattern.sub(f"username password {username}", task, count=1)
        return clean, username, password
    return task, None, None


def post_json(url, key, body):
    for attempt in range(3):
        try:
            response = CLIENT.post(url, json=body, headers={"Authorization": f"Bearer {key}"})
        except httpx.HTTPError:
            if attempt == 2:
                raise RuntimeError("Model connection failed; no action executed.") from None
            time.sleep(0.5 * 2**attempt)
            continue
        if response.status_code in {429, 529, 503} and attempt < 2:
            delay = 0.5 * 2**attempt
            try:
                delay = max(delay, float(response.headers.get("Retry-After", "0")))
            except ValueError:
                pass
            time.sleep(delay)
            continue
        if response.is_error:
            raise RuntimeError(f"Model provider returned HTTP {response.status_code}; no action executed.")
        return response.json()
    raise RuntimeError("Model unavailable")


def validate_choice(answer, ids):
    try:
        probabilities = answer["probabilities"]
        numbers = [*probabilities.values(), answer["confidence"]]
        valid = (
            answer["choice"] in ids
            and set(probabilities) == set(ids)
            and all(type(n) in (int, float) and math.isfinite(n) and 0 <= n <= 1 for n in numbers)
            and abs(sum(probabilities.values()) - 1) < 0.02
            and probabilities[answer["choice"]] >= max(probabilities.values()) - 1e-6
        )
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError("Invalid TypeSafe response; no action executed.")
    return answer


def action_space(actions):
    """One index per observed element; each operation has its own valid target choices."""
    elements, indices, targets, controls = [], {}, {}, {}
    operations = {"click": "CLICK", "fill": "TYPE_TEXT", "select": "SELECT"}
    for action in actions:
        kind = action["kind"]
        if kind not in operations:
            controls[action["id"].upper()] = action
            continue
        node = action["node"]
        if node not in indices:
            index = str(len(elements) + 1)
            indices[node] = index
            element = {k: action[k] for k in ("role", "value", "checked", "selected", "expanded") if k in action}
            element.update(index=index, label=action["label"].split(" → ")[0], operations=[])
            if kind == "select":
                element["value"] = action.get("current_value", "")
                element["options"] = []
            elements.append(element)
        index = indices[node]
        element = elements[int(index) - 1]
        if "risk" in action:
            element["human_risk"] = action["risk"]
        secret = action.get("secret")
        if kind == "fill" and secret and action.get("value"):
            continue  # filled secret: keep the element, offer no fill operation
        if kind == "fill" and secret:
            operation = "TYPE_SECRET" if configured_secret(secret) else "TYPE_TEXT"
        else:
            operation = operations[kind]
        group = targets.setdefault(operation, {})
        if operation not in element["operations"]:
            element["operations"].append(operation)
        target = index
        if kind == "select":
            target = f"{index}:{len(element['options']) + 1}"
            element["options"].append({"index": target, "label": action["label"], "value": action["value"]})
        group[target] = action
    return elements, targets, controls


def _loading_only(actions):
    return bool(actions) and all(action.get("kind") == "wait" for action in actions)


def _loading_decision(operations, choice):
    operation_probabilities = {key: 0.0 for key in operations}
    operation_probabilities["WAIT"] = 1.0
    return {
        "choice": choice,
        "operation": "WAIT",
        "target": None,
        "target_risk": None,
        "human_intervention": 0.0,
        "confidence": 1.0,
        "probabilities": {choice: 1.0},
        "operation_probabilities": operation_probabilities,
        "target_probabilities": {},
        "target_confidence": None,
        "raw_answers": {},
        "model": "loading-fallback",
        "usage": {},
        "latency_ms": 0.0,
        "request": {},
    }


def _fallback_decision(*, choice_id, operation, target, risk, model_name):
    return {
        "choice": choice_id,
        "operation": operation,
        "target": target,
        "target_risk": risk,
        "human_intervention": 0.0,
        "confidence": 1.0,
        "probabilities": {choice_id: 1.0},
        "operation_probabilities": {operation: 1.0},
        "target_probabilities": {target: 1.0},
        "target_confidence": 1.0,
        "raw_answers": {},
        "model": model_name,
        "usage": {},
        "latency_ms": 0.0,
        "request": {},
    }


def _configured_secret_decision(state, targets):
    best = None
    for index, action in targets.get("TYPE_SECRET", {}).items():
        kind = action.get("secret")
        if not kind or not configured_secret(kind) or action.get("value"):
            continue
        rank = SECRET_ORDER.get(kind, 99)
        if best is None or rank < best[0]:
            best = (rank, index, action)
    if best is None:
        return None
    _, index, action = best
    return _fallback_decision(
        choice_id=action["id"], operation="TYPE_SECRET", target=index,
        risk=action.get("risk"), model_name="configured-fallback",
    )


def _login_submit_decision(state, targets):
    passwords = [a for a in state["actions"]
                 if a.get("secret") == "password" and a.get("kind") == "fill"]
    if not passwords or not any(p.get("value") for p in passwords):
        return None
    for action in state["actions"]:
        if action.get("login_form") and action.get("kind") == "fill" and not action.get("value"):
            return None
    pattern = re.compile(r"\b(sign\s*in|log\s*in|login|continue|next|submit)\b", re.I)
    for index, action in targets.get("CLICK", {}).items():
        if not action.get("login_form") or action.get("risk") in {"pay", "otp"}:
            continue
        if pattern.search(action.get("label") or ""):
            return _fallback_decision(
                choice_id=action["id"], operation="CLICK", target=index,
                risk=action.get("risk"), model_name="login-fallback",
            )
    return None


def choose(state, goal, history, *, allow_login_submit=True):
    elements, targets, controls = action_space(state["actions"])
    present = {a.get("secret") for a in state["actions"] if a.get("secret")}
    configured = [kind for kind in SENSITIVE_ENV if kind in present and configured_secret(kind)]
    labels = {
        "CLICK": "Click an element, button, menu option, autocomplete suggestion, or calendar day.",
        "TYPE_TEXT": "Enter or replace text in an editable field. A small LLM will supply the value from the goal.",
        "TYPE_SECRET": "Fill this field with its configured environment secret. "
                       "The value is never shown or sent to a model.",
        "SELECT": "Select an observed dropdown value.",
    }
    operations = {key: labels[key] for key in targets}
    operations.update({key: value["label"] for key, value in controls.items()})
    operations.update(
        NEEDS_HUMAN={
            "what": "A human must complete or authorize this step in the visible browser now.",
            "not_for": "Ordinary clicks/typing the agent can perform, fills backed by "
                       "configured_secrets, or true dead ends (that is BLOCKED).",
            "examples": [
                "CAPTCHA or 'verify you are human' widget is showing",
                "Checkout payment confirmation is waiting",
                "OTP/2FA code from a phone or email is required",
            ],
        },
        DONE="Every requirement is visibly satisfied.",
        BLOCKED="No supported operation can progress.",
    )
    if _loading_only(state["actions"]):
        return _loading_decision(operations, controls["WAIT"]["id"])
    secret_decision = _configured_secret_decision(state, targets)
    if secret_decision is not None:
        return secret_decision
    if allow_login_submit:
        login_decision = _login_submit_decision(state, targets)
        if login_decision is not None:
            return login_decision
    questions = {
        "operation": {"type": "choice", "criteria": operations, "instructions": {"goal": goal, "rules": NEXT_ACTION}}
    }
    questions["human_intervention"] = {"type": "noul", "instructions": HUMAN_INTERVENTION}
    for operation, candidates in targets.items():
        questions[operation.lower() + "_target"] = {
            "type": "choice",
            "criteria": {
                index: {
                    "element": f"[{index}] {a['label']}",
                    "current_value": a.get("current_value", a.get("value", "")),
                    **{k: a[k] for k in ("role", "checked", "selected", "expanded") if k in a},
                    **({"human_risk": a["risk"]} if "risk" in a else {}),
                }
                for index, a in candidates.items()
            },
            "instructions": {"goal": goal, "operation": operation, "rules": [NEXT_ACTION, TARGET]},
        }
    page_state = {k: state[k] for k in ("url", "title", "text")}
    if "page_risks" in state:
        page_state["page_risks"] = state["page_risks"]
    if configured:
        page_state["configured_secrets"] = configured
    body = {
        "model": os.environ.get("TYPESAFE_MODEL", "jev-latest"),
        "state": {
            "page": page_state,
            "elements": elements,
            "recent_actions": [
                {k: h.get(k) for k in ("action", "kind", "text", "page_changed")} for h in history[-10:]
            ],
        },
        "questions": questions,
    }
    started = time.perf_counter()
    base = os.environ.get("TYPESAFE_BASE_URL", "https://api.typesafe.ai").rstrip("/")
    result = post_json(base + "/v1/systemone", os.environ["TYPESAFE_API_KEY"], body)
    operation_answer = validate_choice(result["answers"].get("operation", {}), operations)
    operation = operation_answer["choice"]
    raw_human = result["answers"].get("human_intervention") or {}
    n = raw_human.get("noul")
    human_intervention = float(n) if type(n) in (int, float) and math.isfinite(n) and 0 <= n <= 1 else None
    target = None
    target_answer = None
    probabilities = {}
    if operation in targets:
        # Unused target heads cannot cause an action. Validate the head selected by the operation.
        target_answer = validate_choice(result["answers"].get(operation.lower() + "_target", {}), targets[operation])
        target = target_answer["choice"]
        choice = targets[operation][target]["id"]
        target_risk = targets[operation][target].get("risk")
        probabilities = {a["id"]: target_answer["probabilities"][index] for index, a in targets[operation].items()}
    else:
        choice = controls[operation]["id"] if operation in controls else operation
        target_risk = None
        probabilities[choice] = operation_answer["probabilities"][operation]
    return {
        "choice": choice,
        "operation": operation,
        "target": target,
        "target_risk": target_risk,
        "human_intervention": human_intervention,
        "confidence": operation_answer["confidence"],
        "probabilities": probabilities,
        "operation_probabilities": operation_answer["probabilities"],
        "target_probabilities": target_answer["probabilities"] if target_answer else {},
        "target_confidence": target_answer["confidence"] if target_answer else None,
        "raw_answers": result["answers"],
        "model": result["model"],
        "usage": result.get("usage", {}),
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "request": body,
    }


def field_context(goal, action, page, history):
    return {
        "goal": goal,
        "field": {k: action.get(k) for k in ("label", "role", "value")},
        "page": {"title": page["title"], "text": page["text"][:6000]},
        "recent_actions": [{k: h.get(k) for k in ("action", "text")} for h in history[-6:]],
    }


def field_text(context):
    key = os.environ.get("TEXT_MODEL_API_KEY")
    if not key:
        raise ValueError("TYPE_TEXT needs TEXT_MODEL_API_KEY; no text is hardcoded or guessed by the executor.")
    base = os.environ.get("TEXT_MODEL_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
    model = os.environ.get("TEXT_MODEL", "deepseek-chat")
    reasoning = {"thinking": {"type": "disabled"}} if "api.deepseek.com/" in base else {"reasoning": {"effort": "low"}}
    if os.environ.get("TEXT_MODEL_REASONING") == "none":
        reasoning = {"reasoning": {"enabled": False}}
    started = time.perf_counter()
    result = post_json(
        base + "/chat/completions",
        key,
        {
            "model": model,
            "max_tokens": 1024,
            "response_format": {"type": "json_object"},
            **reasoning,
            "messages": [
                {"role": "system", "content": TEXT_VALUE},
                {
                    "role": "user",
                    "content": json.dumps(context),
                },
            ],
        },
    )
    try:
        content = result["choices"][0]["message"]["content"]
        if isinstance(content, str):
            content = content.strip()
            for stop_token in ("<|im_end|>", "<|endoftext|>"):
                if content.endswith(stop_token):
                    content = content[:-len(stop_token)].strip()
        output = json.loads(content)
        value = output["text"]
        if set(output) != {"text"} or not isinstance(value, str) or not value.strip() or len(value) > 2000:
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise ValueError("Text helper returned no valid field value; nothing typed.") from None
    return value, {
        "model": model,
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "usage": result.get("usage", {}),
    }

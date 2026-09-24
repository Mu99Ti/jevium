"""Deterministic replay of recorded runs. No model calls; drift aborts the run."""

import json

from .model import configured_secret


class ReplayDrift(Exception):
    """A recorded step no longer matches the observed page."""

    def __init__(self, index, reason, url):
        super().__init__(f"step {index}: {reason}")
        self.index = index
        self.reason = reason
        self.url = url


def load_steps(path):
    steps = []
    with open(path) as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                steps.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from None
    if not steps:
        raise ValueError(f"{path}: no steps recorded")
    return steps


def _base(label):
    return label.split(" → ")[0]


def locator_for(action, actions):
    kind = action.get("kind")
    if kind == "wait":
        return {"kind": "wait", "ms": 100}
    if kind == "scroll":
        return {"kind": "scroll", "delta": action.get("delta", 560)}
    role = action.get("role", "")
    name = _base(action.get("label", ""))
    loc = {"kind": kind, "role": role, "name": name}
    if action.get("testid"):
        loc["testid"] = action["testid"]
    if action.get("secret"):
        loc["secret"] = action["secret"]
    if kind == "select":
        nodes = []
        for other in actions:
            if (other.get("kind") == "select" and other.get("role") == role
                    and _base(other.get("label", "")) == name
                    and other.get("node") not in nodes):
                nodes.append(other["node"])
        loc["nth"] = nodes.index(action["node"]) if action.get("node") in nodes else 0
        loc["option_value"] = action.get("value")
        loc["option_label"] = action.get("label", "").split(" → ", 1)[-1]
    else:
        nth = 0
        for other in actions:
            if other is action:
                break
            if (other.get("kind") == kind and other.get("role") == role
                    and _base(other.get("label", "")) == name):
                nth += 1
        loc["nth"] = nth
    return loc


def match_action(page, step):
    actions = page.get("actions") or []
    index = step.get("step", 0)
    url = page.get("url", "")
    kind = step.get("kind")
    if kind == "wait":
        for action in actions:
            if action.get("kind") == "wait":
                return action
        raise ReplayDrift(index, "wait control not present", url)
    if kind == "scroll":
        want = (step.get("locator") or {}).get("delta")
        for action in actions:
            if action.get("kind") == "scroll" and (want is None or action.get("delta") == want):
                return action
        raise ReplayDrift(index, "scroll control not present", url)
    loc = step.get("locator")
    if loc:
        if loc.get("testid"):
            for action in actions:
                if (action.get("testid") == loc["testid"]
                        and action.get("kind") == loc.get("kind", action.get("kind"))):
                    return action
        role, name, nth = loc.get("role"), loc.get("name"), loc.get("nth", 0)
        if kind == "select":
            nodes = []
            for action in actions:
                if (action.get("kind") == "select" and action.get("role") == role
                        and _base(action.get("label", "")) == name
                        and action.get("node") not in nodes):
                    nodes.append(action["node"])
            if nth >= len(nodes):
                raise ReplayDrift(index, f"no element matches {role}/{name!r}#{nth}", url)
            node = nodes[nth]
            for action in actions:
                if action.get("kind") != "select" or action.get("node") != node:
                    continue
                if action.get("value") == loc.get("option_value"):
                    return action
                if action.get("label", "").endswith(" → " + str(loc.get("option_label", ""))):
                    return action
            raise ReplayDrift(index, f"option {loc.get('option_value')!r} not present", url)
        matches = [a for a in actions
                   if a.get("kind") == kind and a.get("role") == role
                   and _base(a.get("label", "")) == name]
        if nth < len(matches):
            return matches[nth]
        reason = (f"testid {loc['testid']!r} no longer present" if loc.get("testid")
                  else f"no element matches {role}/{name!r}#{nth}")
        raise ReplayDrift(index, reason, url)
    choice = step.get("choice")
    for action in actions:
        if action.get("id") == choice and action.get("kind") == kind:
            return action
    raise ReplayDrift(index, f"choice {choice!r} not present", url)


def _resolve_text(step, loc):
    text = step.get("text")
    if text == "***":
        secret = (loc or {}).get("secret")
        value = configured_secret(secret) if secret else ""
        if not value:
            raise ReplayDrift(step.get("step", 0),
                              f"secret {secret!r} not configured in the environment",
                              step.get("url", ""))
        return value
    return text


def replay(browser, steps):
    history = []
    final_page = None
    for step in steps:
        page = browser.observe(screenshot=False)
        final_page = page
        if history:
            history[-1]["url"] = page.get("url", "")
        action = match_action(page, step)
        loc = step.get("locator")
        text = _resolve_text(step, loc) if step.get("kind") == "fill" else None
        browser.act(action, page, text=text)
        history.append({
            "step": len(history) + 1,
            "action": action.get("label") or step.get("action", ""),
            "kind": step.get("kind"),
            "text": text,
            "url": "",
            "page_changed": step.get("page_changed"),
            "locator": loc,
        })
    final_page = browser.observe(screenshot=False)
    if history:
        history[-1]["url"] = final_page.get("url", "")
    return {"status": "done", "history": history, "final_page": final_page}

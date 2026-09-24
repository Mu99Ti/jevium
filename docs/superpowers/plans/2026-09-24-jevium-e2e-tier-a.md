# E2E Tier A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the six Tier-A E2E features (replay, structured verdicts, Playwright test export, CI reports, determinism controls, failure artifacts) as seven individually pushed commits with TDD at every step.

**Architecture:** New single-responsibility modules (`jevium_core/replay.py`, `jevium_core/export_test.py`, `jevium/report.py`) plug into the existing observe → typed choice → execute → verify loop. History entries gain code-owned `locator` hints at execution time; replay and export consume them without any model call. Spec: `docs/superpowers/specs/2026-09-24-jevium-e2e-tier-a-design.md`.

**Tech Stack:** Python 3.12+, Playwright/Chromium, httpx, Textual, pytest, Ruff, Node (`node --check`), `uv`, Git/GitHub.

## Global Constraints

- No model-generated selectors or JavaScript; locators are derived from observed `role`/`name`/`data-testid` only.
- Replay/regression paths make zero paid model calls; tests never call paid APIs; no real credentials in tests (use `not-a-real-secret`).
- Secret values never appear in exports, history (`text="***"`), reports, or artifacts.
- Browser mutations are never retried; replay aborts on the first mismatch with `ReplayDrift`.
- Commit style: `feat: ...` / `docs: ...` lowercase subjects, no body. **Tasks 0–6 each end with an explicit commit and `git push origin main`** (user-requested); Task 7 is evidence-only.
- Checks: `uv run ruff check .` + `uv run pytest -q` after every task; add `node --check jevium_core/snapshot.js` whenever `snapshot.js` changed (Task 1); the final task runs the full suite, both node checks, `uv build`, `git diff --check 688c3cb..HEAD`, the secret scan, and `git ls-remote` verification.
- Do not touch `.playwright-cli/`; keep `.env` out of every commit.
- Tick this plan's checkboxes as each task completes; the ticked plan file is swept into Task 6's commit.

---

### Task 0: Commit design docs

**Files:**
- Already created: `docs/superpowers/specs/2026-09-24-jevium-e2e-tier-a-design.md`
- This file: `docs/superpowers/plans/2026-09-24-jevium-e2e-tier-a.md`

**Interfaces:**
- Produces: nothing executable; establishes the doc baseline for later tasks.

- [ ] **Step 1: Verify the working tree holds only the two doc files**

Run: `git status --porcelain=v1`

Expected: exactly two untracked lines — the spec and this plan file.

- [ ] **Step 2: Commit and push the docs**

```bash
git add docs/superpowers/specs/2026-09-24-jevium-e2e-tier-a-design.md docs/superpowers/plans/2026-09-24-jevium-e2e-tier-a.md
git commit -m "docs: add E2E tier A design and plan"
git push origin main
```

Expected: push reports `688c3cb..<new-sha> main -> main`.

---

### Task 1: A1 — Locator recording and deterministic replay

**Files:**
- Create: `jevium_core/replay.py`
- Create: `tests/test_replay.py`
- Modify: `jevium_core/snapshot.js` (emit `testid`)
- Modify: `jevium_core/agent.py` (record `locator` in history)
- Modify: `jevium/cli.py` (`--replay`, replay branch, key/planner guards, `_start_browser`)
- Modify: `tests/pages/login.html` (add `data-testid`)
- Modify: `tests/test_chromium_live.py`, `tests/test_agent.py`, `tests/test_cli.py`
- Modify: `README.md` (CLI bullet)

**Interfaces:**
- Produces:
  - `replay.ReplayDrift(index: int, reason: str, url: str)` — Exception carrying those attrs.
  - `replay.load_steps(path: str) -> list[dict]` — raises `ValueError` on invalid JSON or an empty file.
  - `replay.locator_for(action: dict, actions: list) -> dict`
  - `replay.match_action(page: dict, step: dict) -> dict`
  - `replay.replay(browser, steps: list) -> {"status": "done", "history": list, "final_page": dict}`
  - CLI: `run --replay STEPS.jsonl` implies plain mode; skips the `TYPESAFE_API_KEY` requirement, the planner, the text-key warning, and the TUI; rejects `--record` with exit2; drift → exit1; load errors → exit2.
  - History entries gain `"locator": {...}`; snapshot actions gain `"testid"` only when `data-testid` exists.

- [x] **Step 1: Write the failing tests**

`tests/pages/login.html` — change the username input line to:

```html
      <input id="user" name="username" autocomplete="username" data-testid="user-field" />
```

In `tests/test_chromium_live.py`, inside `test_login_and_card_secrets_are_masked` after the Username asserts add:

```python
        assert by_label["Username"]["testid"] == "user-field"
```

And append a new test:

```python
def test_actions_without_testid_omit_the_field():
    try:
        browser = chromium.Browser(RISK_PAGE, headless=True)
    except Exception as exc:
        pytest.skip(f"chromium unavailable: {exc}")
    try:
        state = browser.observe(screenshot=False)
        assert all("testid" not in a for a in state["actions"])
    finally:
        browser.close()
```

Append to `tests/test_agent.py`:

```python
def test_history_records_locator_hint(runner):
    runner.state["decision"] = decision("e3")
    runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert runner.state["history"][-1]["locator"] == {
        "kind": "click", "role": "button", "name": "Go", "nth": 0,
    }


def test_secret_fill_records_secret_kind(runner, monkeypatch):
    monkeypatch.setenv("JEVIUM_PASSWORD", "not-a-real-secret")
    runner.state["page"] = login_page()
    runner.state["decision"] = {
        **decision("p1"), "operation": "TYPE_SECRET", "target": "2",
        "target_risk": "credential", "model": "configured-fallback",
    }
    runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    loc = runner.state["history"][-1]["locator"]
    assert loc == {"kind": "fill", "role": "textbox", "name": "Password",
                   "nth": 0, "secret": "password"}
```

Create `tests/test_replay.py`:

```python
"""Replay engine contracts. Offline; a Mock browser stands in for Chromium."""

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
    ]
    loc = replay.locator_for(actions[1], actions)
    assert loc["name"] == "Color" and loc["nth"] == 0
    assert loc["option_value"] == "blue" and loc["option_label"] == "Blue"
    assert replay.locator_for(actions[2], actions)["nth"] == 1


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
```

The file needs `from unittest.mock import Mock` in its imports (add next to `import pytest`).

Append to `tests/test_cli.py`:

```python
def _replay_cli_setup(monkeypatch, tmp_path, body='{"step":1,"kind":"click","choice":"e3"}\n'):
    import jevium_core.chromium as chromium_mod
    import jevium_core.replay as replay_mod

    fresh_env(monkeypatch)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr(planner, "plan", Mock(side_effect=AssertionError("planner must not run")))
    browser = Mock()
    browser_factory = Mock(return_value=browser)
    monkeypatch.setattr(chromium_mod, "Browser", browser_factory)
    steps = tmp_path / "steps.jsonl"
    steps.write_text(body)
    return replay_mod, browser_factory, browser, steps


def test_replay_runs_without_model_key(monkeypatch, tmp_path):
    replay_mod, _factory, browser, steps = _replay_cli_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(replay_mod, "replay", Mock(return_value={
        "status": "done",
        "history": [{"step": 1, "kind": "click", "action": "Go",
                     "url": "https://x.test/done"}],
        "final_page": {"url": "https://x.test/done", "title": "D", "text": ""},
    }))
    code = cli.main(["run", "--url", "https://x.test", "--task", "t",
                     "--replay", str(steps), "--plain"])
    assert code == 0
    replay_mod.replay.assert_called_once()
    browser.close.assert_called_once()


def test_replay_with_record_exits_2(monkeypatch, tmp_path):
    _replay, browser_factory, _browser, steps = _replay_cli_setup(monkeypatch, tmp_path)
    code = cli.main(["run", "--url", "https://x.test", "--task", "t",
                     "--replay", str(steps), "--record", "--plain"])
    assert code == 2
    browser_factory.assert_not_called()


def test_replay_drift_exits_1(monkeypatch, tmp_path, capsys):
    replay_mod, _factory, _browser, steps = _replay_cli_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(replay_mod, "replay", Mock(
        side_effect=replay_mod.ReplayDrift(3, "button 'Go' not found", "https://x.test/step")))
    code = cli.main(["run", "--url", "https://x.test", "--task", "t",
                     "--replay", str(steps), "--plain"])
    assert code == 1
    err = capsys.readouterr().err
    assert "replay drifted at step 3" in err
    assert "button 'Go' not found" in err
    assert "https://x.test/step" in err


def test_replay_missing_file_exits_2_before_browser(monkeypatch, tmp_path):
    _replay, browser_factory, _browser, _steps = _replay_cli_setup(monkeypatch, tmp_path)
    code = cli.main(["run", "--url", "https://x.test", "--task", "t",
                     "--replay", str(tmp_path / "nope.jsonl"), "--plain"])
    assert code == 2
    browser_factory.assert_not_called()
```

`README.md` — after the `--max-steps N` bullet add:

```markdown
- `--replay <steps.jsonl>`: replay a recorded run deterministically, without model calls
```

- [x] **Step 2: Run the tests to verify they fail**

Run:

```bash
uv run pytest -q tests/test_replay.py tests/test_agent.py tests/test_cli.py
uv run pytest -q tests/test_chromium_live.py::test_login_and_card_secrets_are_masked
```

Expected: first command FAILS — `ModuleNotFoundError: No module named 'jevium_core.replay'` plus the two new agent locator tests and the replay CLI tests. Second command FAILS with `KeyError: 'testid'` (if it reports SKIP, run `uv run playwright install chromium` and require FAIL).

- [x] **Step 3: Implement `jevium_core/replay.py`**

Create the module:

```python
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
```

- [x] **Step 4: Implement snapshot `testid`, agent locator recording, and CLI replay**

`jevium_core/snapshot.js` — in the action loop, right after `if (secret) base.secret = secret;` add:

```javascript
    const testid = e.getAttribute('data-testid');
    if (testid) base.testid = testid;
```

`jevium_core/agent.py`:

1. Add to the imports from the core package files:

```python
from .replay import locator_for
```

2. In `command("act")`, add this key inside the `state["history"].append({...})` dict, right after `"kind": action["kind"],`:

```python
                    "locator": locator_for(action, page["actions"]),
```

`jevium/cli.py`:

1. Top-level import, next to the existing `jevium_core` imports:

```python
from jevium_core import replay
```

2. In `parse_args`, after the `--max-steps` argument:

```python
    run.add_argument("--replay", metavar="STEPS", default=None,
                     help="Replay a recorded steps.jsonl without model calls.")
```

3. Guard the model-key requirement:

```python
    if not args.replay and not os.environ.get("TYPESAFE_API_KEY"):
        print("jevium: TYPESAFE_API_KEY is required.", file=sys.stderr)
        return 2
```

4. Guard the text-key warning:

```python
    if not args.replay and not os.environ.get("TEXT_MODEL_API_KEY"):
        print("jevium: warning: no TEXT_MODEL_API_KEY — TYPE_TEXT will abort at the first fill; "
              "planner/verifier skipped.", file=sys.stderr)
```

5. Add a browser starter before `main()`:

```python
def _start_browser(args, profile):
    if args.backend == "chromium":
        try:
            from jevium_core import chromium
        except ImportError as exc:
            raise RuntimeError(f"playwright is not installed ({exc}); run: uv sync") from None
        return chromium.Browser(args.url, headless=args.headless, profile=profile)
    from jevium_core.browser import Browser
    return Browser(args.url)
```

6. Insert the replay branch after the `record_dir` block and before `goals = planner.plan(...)`:

```python
    if args.replay:
        if args.record:
            print("jevium: --record cannot be combined with --replay.", file=sys.stderr)
            return 2
        try:
            steps = replay.load_steps(args.replay)
        except (OSError, ValueError) as exc:
            print(f"jevium: {exc}", file=sys.stderr)
            return 2
        try:
            browser = _start_browser(args, profile)
        except RuntimeError as exc:
            print(f"jevium: {exc}", file=sys.stderr)
            return 2
        try:
            result = replay.replay(browser, steps)
        except replay.ReplayDrift as exc:
            print(f"jevium: replay drifted at step {exc.index}: {exc.reason} (at {exc.url})",
                  file=sys.stderr)
            return 1
        finally:
            browser.close()
        state = {"status": "done", "page": result["final_page"], "elapsed_ms": 0,
                 "history": result["history"], "plan": [args.task]}
        verdict = {"success": None, "reason": "replay completed; verification not configured."}
        print()
        for line in summary_lines(state, verdict):
            print(line)
        return 0
```

- [x] **Step 5: Run the tests to verify they pass**

Run:

```bash
uv run pytest -q tests/test_replay.py tests/test_agent.py tests/test_cli.py
node --check jevium_core/snapshot.js
```

Expected: PASS.

- [x] **Step 6: Run the full suite and linter**

Run: `uv run ruff check . && uv run pytest -q && node --check jevium_core/snapshot.js`

Expected: clean and fully green.

- [x] **Step 7: Tick Task1 checkboxes, commit, push**

Tick this task's `- [ ]` boxes to `- [x]`, then:

```bash
git add jevium_core/replay.py tests/test_replay.py jevium_core/snapshot.js jevium_core/agent.py jevium/cli.py tests/pages/login.html tests/test_chromium_live.py tests/test_agent.py tests/test_cli.py README.md
git commit -m "feat: record locator hints and replay recorded runs"
git push origin main
```

Expected: push succeeds; `git status --porcelain=v1` shows only this plan file modified (checkbox ticks from Task 0/Task 1).

---

### Task 2: A3 — Structured verifier checks

**Files:**
- Modify: `jevium/verifier.py`
- Modify: `jevium/cli.py` (replay verdict wiring)
- Modify: `tests/test_verifier.py`, `tests/test_cli.py`

**Interfaces:**
- Produces: `verifier.verify(goals: list[str], page: dict, history: list[dict], expected_url: str | None = None) -> {"success": bool | None, "reason": str, "checks": list[dict]}`. Check entries are `{"type", "ok", "evidence"}` plus `"optional": true` for `goal_phrase_visible` and `"inconclusive": true` for an unanswerable LLM judge. Replay exits 1 iff `success is False`.

- [x] **Step 1: Write the failing tests**

`tests/test_verifier.py`: add `from unittest.mock import Mock` next to `import json`.

1. In `test_verify_parses_strict_verdict` replace the dict-equality line with:

```python
    out = verifier.verify(GOALS, PAGE, HISTORY)
    assert out["success"] is True and out["reason"] == "results show boots"
    assert {"type": "llm_judge", "ok": True, "evidence": "results show boots"} in out["checks"]
```

2. In `test_verify_retries_once_on_transient_parse_failure` replace the two assertions with:

```python
    assert out["success"] is True and out["reason"] == "ok on retry"
    assert len(calls) == 2
```

3. In `test_verify_failure_is_unknown` replace `assert verifier.verify(GOALS, PAGE, HISTORY)["success"] is None` with:

```python
    out = verifier.verify(GOALS, PAGE, HISTORY)
    assert out["success"] is None
    judge = next(c for c in out["checks"] if c["type"] == "llm_judge")
    assert judge["inconclusive"] is True
```

4. Append:

```python
def test_expected_url_mismatch_fails_without_llm(monkeypatch):
    monkeypatch.delenv("TEXT_MODEL_API_KEY", raising=False)
    monkeypatch.setattr(llm, "chat_json", Mock(side_effect=AssertionError("llm must not run")))
    out = verifier.verify(GOALS, PAGE, HISTORY, expected_url="https://shop.test/other")
    assert out["success"] is False
    check = out["checks"][0]
    assert check["type"] == "expected_url" and check["ok"] is False
    assert "https://shop.test/other" in check["evidence"]


def test_expected_url_match_without_llm_is_success(monkeypatch):
    monkeypatch.delenv("TEXT_MODEL_API_KEY", raising=False)
    out = verifier.verify(GOALS, PAGE, HISTORY, expected_url="https://shop.test/results")
    assert out["success"] is True
    types = [c["type"] for c in out["checks"]]
    assert "expected_url" in types and "goal_phrase_visible" in types


def test_goal_phrase_check_is_optional(monkeypatch):
    monkeypatch.delenv("TEXT_MODEL_API_KEY", raising=False)
    out = verifier.verify(["Nonexistent zebra goal"], PAGE, HISTORY,
                          expected_url="https://shop.test/results")
    phrase = next(c for c in out["checks"] if c["type"] == "goal_phrase_visible")
    assert phrase["ok"] is False and phrase["optional"] is True
    assert out["success"] is True


def test_llm_false_answer_is_required_failure(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    monkeypatch.setattr(llm, "chat_json",
                        lambda *a, **k: json.dumps({"success": False, "reason": "cart empty"}))
    out = verifier.verify(GOALS, PAGE, HISTORY, expected_url="https://shop.test/results")
    assert out["success"] is False
    judge = next(c for c in out["checks"] if c["type"] == "llm_judge")
    assert judge["ok"] is False and judge["evidence"] == "cart empty"
```

Append to `tests/test_cli.py`:

```python
def test_replay_passes_expected_url_and_exits_by_verdict(monkeypatch, tmp_path):
    replay_mod, _factory, _browser, steps = _replay_cli_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(replay_mod, "replay", Mock(return_value={
        "status": "done",
        "history": [{"step": 1, "kind": "click", "action": "Go", "url": "https://x.test/done"}],
        "final_page": {"url": "https://x.test/done", "title": "D", "text": ""},
    }))
    captured = {}

    def fake_verify(goals, page, history, expected_url=None):
        captured["expected_url"] = expected_url
        return {"success": True, "reason": "ok", "checks": []}

    monkeypatch.setattr(cli.verifier, "verify", fake_verify)
    code = cli.main(["run", "--url", "https://x.test", "--task", "t",
                     "--replay", str(steps), "--plain"])
    assert code == 0
    assert captured["expected_url"] == "https://x.test/done"


def test_replay_verdict_false_exits_1(monkeypatch, tmp_path):
    replay_mod, _factory, _browser, steps = _replay_cli_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(replay_mod, "replay", Mock(return_value={
        "status": "done",
        "history": [{"step": 1, "kind": "click", "action": "Go", "url": "https://x.test/other"}],
        "final_page": {"url": "https://x.test/other", "title": "D", "text": ""},
    }))
    monkeypatch.setattr(cli.verifier, "verify",
                        lambda *a, **k: {"success": False, "reason": "url mismatch", "checks": []})
    code = cli.main(["run", "--url", "https://x.test", "--task", "t",
                     "--replay", str(steps), "--plain"])
    assert code == 1
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest -q tests/test_verifier.py tests/test_cli.py -k "expected_url or goal_phrase or llm_false or failure_is_unknown or strict_verdict or retries_once or replay_passes or replay_verdict" -v`

Expected: FAIL — `KeyError: 'checks'` on the new verifier assertions (old return shape), and `expected_url` capture is `None` / exit-code mismatch because the replay branch does not pass or honor the verdict yet.

- [x] **Step 3: Implement structured verdicts**

Replace the entire body of `verifier.verify` in `jevium/verifier.py` (keep `SYSTEM` and imports unchanged):

```python
def verify(goals: list[str], page: dict, history: list[dict], expected_url: str | None = None) -> dict:
    checks = []
    if expected_url is not None:
        actual = page.get("url", "")
        ok = actual == expected_url
        checks.append({"type": "expected_url", "ok": ok,
                       "evidence": f"expected {expected_url!r}, got {actual!r}"})
        if not ok:
            return {"success": False, "reason": checks[0]["evidence"], "checks": checks}
    page_text = (page.get("text") or "").lower()
    for goal in goals:
        found = bool(goal.strip()) and goal.strip().lower() in page_text
        checks.append({"type": "goal_phrase_visible", "ok": found, "optional": True,
                       "evidence": f"goal {goal!r} {'found in' if found else 'not found in'} page text"})
    if not os.environ.get("TEXT_MODEL_API_KEY"):
        if expected_url is not None:
            return {"success": True,
                    "reason": "deterministic checks passed; verifier skipped.",
                    "checks": checks}
        return {"success": None, "reason": "verifier skipped: no TEXT_MODEL_API_KEY.",
                "checks": checks}
    steps = [
        {k: h.get(k) for k in ("action", "kind", "text", "url")}
        for h in history[-30:]
    ]
    user = json.dumps({
        "goals": goals,
        "final_page": {
            "url": page.get("url", ""),
            "title": page.get("title", ""),
            "text": (page.get("text") or "")[:6000],
        },
        "recent_actions": steps,
    })
    last = "verifier failed: no attempt completed."
    for _attempt in range(2):
        try:
            out = json.loads(llm.chat_json(SYSTEM, user))
        except (ValueError, OSError, RuntimeError) as exc:
            last = f"verifier failed: {exc}"
            continue
        if (not isinstance(out, dict) or not isinstance(out.get("success"), bool)
                or not isinstance(out.get("reason"), str)):
            last = "verifier returned an invalid verdict."
            continue
        checks.append({"type": "llm_judge", "ok": out["success"], "evidence": out["reason"]})
        return {"success": out["success"], "reason": out["reason"], "checks": checks}
    checks.append({"type": "llm_judge", "ok": False, "inconclusive": True, "evidence": last})
    return {"success": None, "reason": last, "checks": checks}
```

In `jevium/cli.py`'s replay branch, replace the hardcoded verdict block with:

```python
        verdict = verifier.verify(
            [args.task], result["final_page"], result["history"],
            expected_url=steps[-1].get("url"),
        )
        print()
        for line in summary_lines(state, verdict):
            print(line)
        return 0 if verdict.get("success") is not False else 1
```

(`state` stays exactly as Task1 built it.)

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run ruff check . && uv run pytest -q`

Expected: full suite green (verdict shape tests, replay exit tests, unchanged non-replay callers, fresh_env verifier stubs still compatible).

- [x] **Step 5: Tick Task2 checkboxes, commit, push**

```bash
git add jevium/verifier.py jevium/cli.py tests/test_verifier.py tests/test_cli.py
git commit -m "feat: return structured verifier checks"
git push origin main
```

---

### Task 3: A2 — Playwright Test export

**Files:**
- Create: `jevium_core/export_test.py`
- Create: `tests/test_export_test.py`
- Modify: `jevium/cli.py` (`--export-test`, `run_plain` export, replay export)
- Modify: `jevium/tui.py` (`run_tui`/`_finish` export; new params)
- Modify: `tests/test_cli.py`, `tests/test_tui.py`
- Modify: `README.md`

**Interfaces:**
- Produces: `export_test.render_playwright_test(*, task: str, start_url: str, history: list[dict], final_page: dict) -> str`.
- CLI/TUI flag `--export-test PATH`. Export runs only when `status == "done"`; otherwise stderr `jevium: export skipped: run did not complete` and the original exit code is preserved. Secret steps emit `process.env.<VAR>!` and never a literal. `run_plain`/`run_tui`/`JeviumApp` gain `report_path` parameters in this task but wire them only in Task 4.

- [x] **Step 1: Write the failing tests**

Create `tests/test_export_test.py`:

```python
"""Playwright Test export rendering. Pure string contracts; no browser, no model."""

import json

from jevium_core import export_test


def render(history, task="Find boots", start_url="https://x.test/"):
    return export_test.render_playwright_test(
        task=task, start_url=start_url, history=history,
        final_page={"url": "https://x.test/done", "title": "Done"},
    )


def test_goto_role_click_and_final_assertions():
    out = render([{"step": 1, "kind": "click", "text": None, "locator": {
        "kind": "click", "role": "button", "name": "Go", "nth": 0}}])
    assert "import { test, expect } from" in out
    assert 'test("Find boots", async ({ page }) => {' in out
    assert 'await page.goto("https://x.test/");' in out
    assert 'page.getByRole("button", { name: "Go" })' in out
    assert ".click();" in out
    assert ".nth(" not in out
    assert 'await expect(page).toHaveURL("https://x.test/done");' in out
    assert 'await expect(page).toHaveTitle("Done");' in out


def test_fill_uses_json_string_escaping_and_nth():
    text = 'say "hi"\nnext'
    out = render([{"step": 1, "kind": "fill", "text": text, "locator": {
        "kind": "fill", "role": "textbox", "name": "Search", "nth": 2}}])
    assert ".nth(2)" in out
    assert (".fill(" + json.dumps(text) + ");") in out


def test_secret_fill_uses_env_never_literal():
    out = render([{"step": 1, "kind": "fill", "text": "***", "locator": {
        "kind": "fill", "role": "textbox", "name": "Password", "nth": 0,
        "secret": "password"}}])
    assert "process.env.JEVIUM_PASSWORD!" in out
    assert '"***"' not in out


def test_testid_preferred_over_role():
    out = render([{"step": 1, "kind": "click", "text": None, "locator": {
        "kind": "click", "role": "button", "name": "Go", "nth": 0,
        "testid": "submit-btn"}}])
    assert 'page.getByTestId("submit-btn")' in out
    assert "getByRole" not in out


def test_select_wait_and_scroll():
    out = render([
        {"step": 1, "kind": "select", "text": None, "locator": {
            "kind": "select", "role": "combobox", "name": "Color", "nth": 0,
            "option_value": "red", "option_label": "Red"}},
        {"step": 2, "kind": "wait", "text": None, "locator": {"kind": "wait", "ms": 100}},
        {"step": 3, "kind": "scroll", "text": None, "locator": {"kind": "scroll", "delta": -560}},
    ])
    assert '.selectOption("red");' in out
    assert "await page.waitForTimeout(100);" in out
    assert "await page.mouse.wheel({ deltaY: -560 });" in out


def test_legacy_step_without_locator_is_commented():
    out = render([{"step": 9, "kind": "click", "text": None, "choice": "e9"}])
    assert "// skipped step 9: no recorded locator" in out
```

Append to `tests/test_cli.py`:

```python
def test_export_test_written_on_done(monkeypatch, tmp_path):
    fresh_env(monkeypatch)
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")

    class Exportable(FakeAgent):
        def run(self, on_waiting=None):
            yield {
                "status": "done", "elapsed_ms": 10, "history": [{
                    "step": 1, "action": "Click Go", "kind": "click", "text": None,
                    "url": "https://x.test/done",
                    "locator": {"kind": "click", "role": "button", "name": "Go", "nth": 0},
                }],
                "page": {"url": "https://x.test/done", "title": "Done", "text": "done"},
                "waiting": None, "plan": ["t"],
            }

    monkeypatch.setattr(cli, "Agent", Exportable)
    out = tmp_path / "specs" / "flow.spec.ts"
    code = cli.main(["run", "--url", "https://x.test", "--task", "t",
                     "--plain", "--export-test", str(out)])
    assert code == 0
    text = out.read_text()
    assert 'page.getByRole("button", { name: "Go" })' in text
    assert 'await page.goto("https://x.test");' in text


def test_export_skipped_when_not_done(monkeypatch, tmp_path, capsys):
    fresh_env(monkeypatch)
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")

    class Blocked(FakeAgent):
        def run(self, on_waiting=None):
            yield {"status": "blocked", "elapsed_ms": 5, "history": [],
                   "page": {"url": "https://x.test/", "title": "t", "text": ""},
                   "waiting": None, "plan": ["t"]}

    monkeypatch.setattr(cli, "Agent", Blocked)
    out = tmp_path / "flow.spec.ts"
    code = cli.main(["run", "--url", "https://x.test", "--task", "t",
                     "--plain", "--export-test", str(out)])
    assert code == 1
    assert not out.exists()
    assert "export skipped" in capsys.readouterr().err
```

In `tests/test_cli.py`:

1. Change the `fake_run_tui` in `test_tui_defers_agent_creation_until_tui_worker` to accept the new kwargs:

```python
    def fake_run_tui(agent_factory, *, goals, max_steps=None, **_kw):
```

2. Append the new finish test to `tests/test_tui.py` (inside `run_test` so widgets exist):

```python
def test_finish_renders_export_when_done(tmp_path, monkeypatch):
    from unittest.mock import Mock as _Mock
    monkeypatch.setattr(tui.verifier, "verify",
                        lambda *a, **k: {"success": True, "reason": "ok", "checks": []})
    target = tmp_path / "out" / "flow.spec.ts"
    app = tui.JeviumApp(lambda: None, goals=["t"], max_steps=60,
                        export_path=str(target), start_url="https://x.test/")
    app.run_worker = lambda *args, **kwargs: None
    app.exit = _Mock()
    state = {
        "status": "done", "elapsed_ms": 10,
        "history": [{"step": 1, "action": "Go", "kind": "click", "text": None,
                     "url": "https://x.test/done",
                     "locator": {"kind": "click", "role": "button", "name": "Go", "nth": 0}}],
        "page": {"url": "https://x.test/done", "title": "Done", "text": "done"},
        "waiting": None, "plan": ["t"],
    }

    async def finish():
        async with app.run_test(size=(80, 24)):
            app._finish(state)

    asyncio.run(finish)
    assert target.exists()
    assert 'page.getByRole("button", { name: "Go" })' in target.read_text()
```

(`JeviumApp.__init__` does not accept `export_path`/`start_url` yet — the test is red on `TypeError`, which is the point.)

`README.md` — after the `--replay` bullet add:

```markdown
- `--export-test <path.spec.ts>`: write a deterministic Playwright Test from a completed run or replay
```

- [x] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest -q tests/test_export_test.py tests/test_tui.py::test_finish_renders_export_when_done
uv run pytest -q tests/test_cli.py -k export
```

Expected: FAIL — `ModuleNotFoundError: No module named 'jevium_core.export_test'`; TUI `TypeError: __init__() got an unexpected keyword argument 'export_path'`; CLI file-not-created / missing skip notice.

- [x] **Step 3: Implement export rendering and wiring**

Create `jevium_core/export_test.py`:

```python
"""Render a recorded run as a deterministic Playwright Test. Code-owned locators only."""

import json

from .model import SENSITIVE_ENV


def _locator_expr(loc):
    if loc.get("testid"):
        expr = f"page.getByTestId({json.dumps(loc['testid'])})"
    elif loc.get("role") is not None and loc.get("name") is not None:
        expr = (f"page.getByRole({json.dumps(loc['role'])}, "
                f"{{ name: {json.dumps(loc['name'])} }})")
    else:
        return None
    nth = int(loc.get("nth", 0) or 0)
    if nth:
        expr += f".nth({nth})"
    return expr


def render_playwright_test(*, task, start_url, history, final_page) -> str:
    lines = [
        "import { test, expect } from '@playwright/test';",
        "",
        f"test({json.dumps(task)}, async ({{ page }}) => {{",
        f"  await page.goto({json.dumps(start_url)});",
    ]
    for step in history:
        loc = step.get("locator") or {}
        kind = step.get("kind")
        if kind == "wait":
            lines.append(f"  await page.waitForTimeout({int(loc.get('ms', 100))});")
            continue
        if kind == "scroll":
            lines.append(f"  await page.mouse.wheel({{ deltaY: {int(loc.get('delta', 560))} }});")
            continue
        expr = _locator_expr(loc)
        if expr is None:
            lines.append(f"  // skipped step {step.get('step')}: no recorded locator")
            continue
        if kind == "fill":
            if loc.get("secret"):
                lines.append(f"  await {expr}.fill(process.env.{SENSITIVE_ENV[loc['secret']]}!);")
            else:
                lines.append(f"  await {expr}.fill({json.dumps(step.get('text') or '')});")
        elif kind == "select":
            option = loc.get("option_value")
            lines.append(f"  await {expr}.selectOption({json.dumps(option if option is not None else '')});")
        else:
            lines.append(f"  await {expr}.click();")
    lines += [
        f"  await expect(page).toHaveURL({json.dumps(final_page.get('url', ''))});",
        f"  await expect(page).toHaveTitle({json.dumps(final_page.get('title', ''))});",
        "});",
        "",
    ]
    return "\n".join(lines)
```

`jevium/cli.py`:

1. Top import: `from jevium_core.export_test import render_playwright_test`
2. Parse arg after `--replay`:

```python
    run.add_argument("--export-test", metavar="PATH", default=None,
                     help="Write a Playwright Test spec after a completed run.")
```

3. `run_plain` signature becomes (the `report_path` parameter is accepted now and wired in Task4):

```python
def run_plain(agent, goals, *, max_steps=None, export_path=None, report_path=None, start_url=None):
```

4. In `run_plain`, after the summary loop and before the `return`:

```python
    if export_path:
        if final.get("status") == "done":
            try:
                path = Path(export_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(render_playwright_test(
                    task="; ".join(str(g) for g in goals),
                    start_url=start_url or "",
                    history=final.get("history") or [],
                    final_page=final.get("page") or {},
                ))
            except OSError as exc:
                print(f"jevium: export failed: {exc}", file=sys.stderr)
        else:
            print("jevium: export skipped: run did not complete", file=sys.stderr)
```

5. `main()`'s `run_plain(...)` call becomes:

```python
            return run_plain(agent, goals, max_steps=args.max_steps,
                             export_path=args.export_test, start_url=args.url)
```

6. In the replay branch, after `state` and `verdict` are built and before the summary print:

```python
        if args.export_test:
            try:
                path = Path(args.export_test)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(render_playwright_test(
                    task=args.task, start_url=args.url,
                    history=result["history"], final_page=result["final_page"],
                ))
            except OSError as exc:
                print(f"jevium: export failed: {exc}", file=sys.stderr)
```

7. TUI dispatch becomes:

```python
        return run_tui(create_agent, goals=goals, max_steps=args.max_steps,
                       export_path=args.export_test, start_url=args.url)
```

`jevium/tui.py`:

1. Add `from pathlib import Path` and `from jevium_core.export_test import render_playwright_test` to the imports.
2. `JeviumApp.__init__` becomes `def __init__(self, agent_factory, *, goals, max_steps=None, export_path=None, start_url=None, report_path=None):` storing `self.export_path = export_path`, `self.start_url = start_url`, `self.report_path = report_path`.
3. `run_tui` becomes `def run_tui(agent_factory, *, goals, max_steps=None, export_path=None, start_url=None, report_path=None) -> int:` passing all three through to `JeviumApp`.
4. In `_finish`, after the summary lines are written to the log and before `self.exit_code = ...`:

```python
        if self.export_path:
            if final.get("status") == "done":
                try:
                    target = Path(self.export_path)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(render_playwright_test(
                        task="; ".join(str(g) for g in self.goals),
                        start_url=self.start_url or "",
                        history=final.get("history") or [],
                        final_page=final.get("page") or {},
                    ))
                except OSError as exc:
                    log.write(f"jevium: export failed: {exc}")
            else:
                log.write("jevium: export skipped: run did not complete")
```

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run ruff check . && uv run pytest -q`

Expected: full suite green (export render tests, CLI export tests, TUI finish test, updated `fake_run_tui`).

- [x] **Step 5: Tick Task3 checkboxes, commit, push**

```bash
git add jevium_core/export_test.py tests/test_export_test.py jevium/cli.py jevium/tui.py tests/test_cli.py tests/test_tui.py README.md
git commit -m "feat: export Playwright tests from recorded runs"
git push origin main
```

---

### Task 4: A4 — JUnit and JSON run reports

**Files:**
- Create: `jevium/report.py`
- Create: `tests/test_report.py`
- Modify: `jevium/cli.py` (`--report`, suffix validation, `run_plain`/replay report writes)
- Modify: `jevium/tui.py` (`_finish` report write; dispatch passes the flag)
- Modify: `tests/test_cli.py`, `tests/test_tui.py`
- Modify: `README.md`

**Interfaces:**
- Produces: `report.report_format(path) -> "json" | "xml" | None`; `report.report_payload(state, verdict) -> dict`; `report.render_report(state, verdict, fmt) -> str`.
- Payload keys: `goals, status, success, reason, checks, actions, elapsed_ms, final_url, tokens:{input,output}, text_model_calls, model_ids`.
- CLI flag `--report PATH`; an unknown suffix exits2 before any browser starts.

- [x] **Step 1: Write the failing tests**

Create `tests/test_report.py`:

```python
"""CI report rendering: JSON payload and JUnit XML. Offline only."""

import json
import xml.etree.ElementTree as ET

from jevium import report

STATE = {
    "status": "done",
    "plan": ["t1"],
    "history": [{"usage": {"input_tokens": 10, "output_tokens": 2}}],
    "text_calls": [{"usage": {"prompt_tokens": 5, "completion_tokens": 3}}],
    "elapsed_ms": 1500,
    "page": {"url": "https://x.test/done"},
    "decisions": [{"model": "jev-1.13.0"}, {"model": "jev-1.13.0"}],
}
VERDICT = {"success": False, "reason": "url mismatch",
           "checks": [{"type": "expected_url", "ok": False, "evidence": "e"}]}


def test_report_format_by_suffix(tmp_path):
    assert report.report_format(str(tmp_path / "r.json")) == "json"
    assert report.report_format(str(tmp_path / "r.xml")) == "xml"
    assert report.report_format(str(tmp_path / "r.txt")) is None


def test_payload_normalizes_tokens_and_models():
    payload = report.report_payload(STATE, VERDICT)
    assert payload["tokens"] == {"input": 15, "output": 5}
    assert payload["model_ids"] == ["jev-1.13.0"]
    assert payload["actions"] == 1
    assert payload["final_url"] == "https://x.test/done"
    assert payload["success"] is False


def test_render_json_roundtrip():
    payload = json.loads(report.render_report(STATE, VERDICT, "json"))
    assert payload["reason"] == "url mismatch"
    assert payload["checks"][0]["type"] == "expected_url"


def test_junit_failure_and_skip_and_pass():
    failed = ET.fromstring(report.render_report(STATE, VERDICT, "xml"))
    assert failed.tag == "testsuite" and failed.get("name") == "jevium"
    case = failed.find("testcase")
    assert case.get("name") == "t1"
    assert case.find("failure") is not None
    unknown = ET.fromstring(report.render_report(
        STATE, {"success": None, "reason": "skipped", "checks": []}, "xml"))
    assert unknown.find("testcase").find("skipped") is not None
    passed = ET.fromstring(report.render_report(
        STATE, {"success": True, "reason": "ok", "checks": []}, "xml"))
    assert passed.find("testcase").find("failure") is None
    assert passed.find("testcase").find("skipped") is None
```

Append to `tests/test_cli.py` (add `import json` to that file's top imports in this step):

```python
def test_report_bad_suffix_exits_2(monkeypatch, capsys):
    fresh_env(monkeypatch)
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    code = cli.main(["run", "--url", "https://x.test", "--task", "t",
                     "--plain", "--report", "out.txt"])
    assert code == 2
    assert "--report must end in .json or .xml" in capsys.readouterr().err


def test_report_json_written_on_run(monkeypatch, tmp_path):
    fresh_env(monkeypatch)
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    monkeypatch.setattr(cli, "Agent", FakeAgent)
    target = tmp_path / "ci" / "r.json"
    code = cli.main(["run", "--url", "https://x.test", "--task", "t",
                     "--plain", "--report", str(target)])
    assert code == 0
    payload = json.loads(target.read_text())
    assert payload["status"] == "done"
    assert "tokens" in payload and payload["checks"] == []


def test_replay_writes_report(monkeypatch, tmp_path):
    replay_mod, _factory, _browser, steps = _replay_cli_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(replay_mod, "replay", Mock(return_value={
        "status": "done",
        "history": [{"step": 1, "kind": "click", "action": "Go", "url": "https://x.test/done"}],
        "final_page": {"url": "https://x.test/done", "title": "D", "text": ""},
    }))
    target = tmp_path / "replay.json"
    code = cli.main(["run", "--url", "https://x.test", "--task", "t",
                     "--replay", str(steps), "--plain", "--report", str(target)])
    assert code == 0
    assert json.loads(target.read_text())["status"] == "done"
```

In `tests/test_tui.py`, extend the Task3 test `test_finish_renders_export_when_done`: change the constructor to `report_path=str(tmp_path / "r.xml")` (third kwarg) and append:

```python
    assert (tmp_path / "r.xml").exists()
    assert (tmp_path / "r.xml").read_text().startswith("<testsuite")
```

`README.md` — after the `--export-test` bullet add:

```markdown
- `--report <path.json|path.xml>`: write a machine-readable run report (JSON or JUnit XML) for CI
```

- [x] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest -q tests/test_report.py
uv run pytest -q tests/test_cli.py -k report
uv run pytest -q tests/test_tui.py::test_finish_renders_export_when_done
```

Expected: FAIL — `ModuleNotFoundError: No module named 'jevium.report'`; CLI missing `--report` handling (bad-suffix message assertion fails, report file not created); TUI `r.xml` missing.

- [x] **Step 3: Implement report module and wiring**

Create `jevium/report.py`:

```python
"""Machine-readable run reports for CI: JSON payload and JUnit XML."""

import json
import xml.etree.ElementTree as ET


def report_format(path):
    text = str(path)
    if text.endswith(".json"):
        return "json"
    if text.endswith(".xml"):
        return "xml"
    return None


def _token_totals(state):
    inp = out = 0
    for entry in list(state.get("history") or []) + list(state.get("text_calls") or []):
        usage = entry.get("usage") or {}
        inp += int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        out += int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
    return {"input": inp, "output": out}


def report_payload(state, verdict):
    page = state.get("page") or {}
    model_ids = sorted({d.get("model") for d in (state.get("decisions") or []) if d.get("model")})
    return {
        "goals": state.get("plan") or [],
        "status": state.get("status"),
        "success": verdict.get("success"),
        "reason": verdict.get("reason"),
        "checks": verdict.get("checks") or [],
        "actions": len(state.get("history") or []),
        "elapsed_ms": state.get("elapsed_ms", 0),
        "final_url": page.get("url", ""),
        "tokens": _token_totals(state),
        "text_model_calls": len(state.get("text_calls") or []),
        "model_ids": model_ids,
    }


def render_report(state, verdict, fmt):
    payload = report_payload(state, verdict)
    if fmt == "json":
        return json.dumps(payload, indent=2) + "\n"
    elapsed = f"{payload['elapsed_ms'] / 1000:.3f}"
    suite = ET.Element("testsuite", name="jevium", tests="1", time=elapsed)
    goal = str(payload["goals"][0]) if payload["goals"] else "jevium run"
    case = ET.SubElement(suite, "testcase", classname="jevium", name=goal, time=elapsed)
    if payload["success"] is False:
        failure = ET.SubElement(case, "failure", message=str(payload["reason"])[:500])
        failure.text = json.dumps(payload["checks"])
    elif payload["success"] is None:
        ET.SubElement(case, "skipped", message=str(payload["reason"])[:500])
    system_out = ET.SubElement(case, "system-out")
    system_out.text = json.dumps(payload, indent=2)
    ET.indent(suite, space="  ")
    return ET.tostring(suite, encoding="unicode") + "\n"
```

`jevium/cli.py`:

1. Top import next to the other relative imports: `from .report import render_report, report_format`
2. Parse arg after `--export-test`:

```python
    run.add_argument("--report", metavar="PATH", default=None,
                     help="Write a JSON or JUnit XML run report (CI).")
```

3. Validation directly after the configured-secret task guard:

```python
    if args.report and report_format(args.report) is None:
        print("jevium: --report must end in .json or .xml", file=sys.stderr)
        return 2
```

4. In `run_plain`, after the export block and before the `return` statements:

```python
    if report_path:
        fmt = report_format(report_path)
        try:
            path = Path(report_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(render_report(final, verdict, fmt))
        except OSError as exc:
            print(f"jevium: report failed: {exc}", file=sys.stderr)
```

5. `main()`'s `run_plain(...)` call gains `report_path=args.report` (now the argument exists):

```python
            return run_plain(agent, goals, max_steps=args.max_steps,
                             export_path=args.export_test, report_path=args.report,
                             start_url=args.url)
```

6. Replay branch — after `verdict` is built, before the export/summary print:

```python
        if args.report:
            try:
                path = Path(args.report)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(render_report(state, verdict, report_format(args.report)))
            except OSError as exc:
                print(f"jevium: report failed: {exc}", file=sys.stderr)
```

7. TUI dispatch gains the flag: `..., report_path=args.report)`.

`jevium/tui.py`:

1. Top import: `from .report import render_report, report_format`
2. In `_finish`, after the export block and before `self.exit_code = ...`:

```python
        if self.report_path:
            fmt = report_format(self.report_path)
            try:
                target = Path(self.report_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(render_report(final, verdict, fmt))
            except OSError as exc:
                log.write(f"jevium: report failed: {exc}")
```

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run ruff check . && uv run pytest -q`

Expected: full suite green.

- [x] **Step 5: Tick Task4 checkboxes, commit, push**

```bash
git add jevium/report.py tests/test_report.py jevium/cli.py jevium/tui.py tests/test_cli.py tests/test_tui.py README.md
git commit -m "feat: add JUnit and JSON run reports"
git push origin main
```

---

### Task 5: A5 — E2E determinism controls

**Files:**
- Modify: `jevium_core/chromium.py` (`reduced_motion`, `wait_idle`, `settle`)
- Modify: `jevium_core/browser.py` (`settle` hook in `observe`)
- Modify: `jevium/cli.py` (`--wait-idle`, restriction, factory wiring)
- Modify: `tests/test_cli.py`, `tests/test_chromium_live.py`
- Modify: `README.md`

**Interfaces:**
- Produces: Playwright contexts created with `reduced_motion="reduce"`; `BaseBrowser.settle()` invoked at the top of every `observe()`; chromium `settle()` waits `networkidle` (1s cap, swallowed timeout) only when `wait_idle=True`; CLI `--wait-idle` is chromium-only (harness → exit2).

- [x] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
def test_harness_rejects_wait_idle(monkeypatch, capsys):
    fresh_env(monkeypatch)
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    code = cli.main(["run", "--url", "https://x.test", "--task", "t",
                     "--backend", "harness", "--wait-idle", "--plain"])
    assert code == 2
    assert "--wait-idle require --backend chromium" in capsys.readouterr().err
```

Append to `tests/test_chromium_live.py`:

```python
def test_reduced_motion_and_wait_idle():
    try:
        b = chromium.Browser(RISK_PAGE, headless=True, wait_idle=True)
    except TypeError:
        raise  # our missing parameter is a bug, not an environment skip
    except Exception as exc:
        pytest.skip(f"chromium unavailable: {exc}")
    try:
        assert b.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches") is True
        assert b.wait_idle is True
        b.settle()  # loaded fixture page: networkidle resolves or is swallowed
    finally:
        b.close()
```

`README.md` — after the `--report` bullet add:

```markdown
- `--wait-idle`: wait for network idle after each observation (chromium backend only; pairs with the default reduced-motion emulation)
```

- [x] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest -q tests/test_cli.py::test_harness_rejects_wait_idle
uv run pytest -q tests/test_chromium_live.py::test_reduced_motion_and_wait_idle
```

Expected: FAIL — CLI message assertion fails (argparse "unrecognized arguments" text, code2 for the wrong reason); live test raises `TypeError: Browser.__init__() got an unexpected keyword argument 'wait_idle'` (TypeError must propagate, not skip).

- [x] **Step 3: Implement determinism controls**

`jevium_core/chromium.py`:

1. Change the constructor signature and store the flag at the top of the body:

```python
    def __init__(self, url, *, headless=False, profile=None, wait_idle=False):
        self.wait_idle = wait_idle
        self._pw = sync_playwright().start()
```

2. Add `reduced_motion="reduce"` to both context constructors:

```python
                self._context = self._pw.chromium.launch_persistent_context(
                    str(user_data), headless=headless, viewport=viewport,
                    reduced_motion="reduce",
                )
```

```python
                self._context = self._browser.new_context(
                    viewport=viewport, reduced_motion="reduce")
```

3. Add the settle override after the `call` method:

```python
    def settle(self):
        if not getattr(self, "wait_idle", False) or not getattr(self, "page", None):
            return
        try:
            self.page.wait_for_load_state("networkidle", timeout=1000)
        except Exception:
            pass
```

`jevium_core/browser.py`:

1. Add the default hook on `BaseBrowser` (before `observe`):

```python
    def settle(self):
        return None
```

2. Make `observe` call it — insert as the first statement of `observe`'s body:

```python
    def observe(self, screenshot=True):
        self.settle()
        if getattr(self, "after_input", None):
```

`jevium/cli.py`:

1. Parse arg:

```python
    run.add_argument("--wait-idle", action="store_true",
                     help="Wait for network idle after each observation (chromium only).")
```

2. Extend the harness restriction:

```python
    if args.backend == "harness" and (args.headless or args.profile or args.wait_idle):
        print("jevium: --headless/--profile/--wait-idle require --backend chromium.", file=sys.stderr)
        return 2
```

3. Chromium factory partial gains the flag:

```python
        browser_factory = partial(chromium.Browser, headless=args.headless,
                                  profile=profile, wait_idle=args.wait_idle)
```

4. `_start_browser` chromium branch gains it too:

```python
        return chromium.Browser(args.url, headless=args.headless, profile=profile,
                                wait_idle=args.wait_idle)
```

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run ruff check . && uv run pytest -q`

Expected: full suite green (both new tests plus existing harness/profile restriction tests).

- [x] **Step 5: Tick Task5 checkboxes, commit, push**

```bash
git add jevium_core/chromium.py jevium_core/browser.py jevium/cli.py tests/test_cli.py tests/test_chromium_live.py README.md
git commit -m "feat: add E2E determinism controls"
git push origin main
```

---

### Task 6: A6 — Failure artifacts

**Files:**
- Modify: `jevium_core/browser.py` (default `save_failure_artifacts`)
- Modify: `jevium_core/chromium.py` (tracing, network log, save override, close stop)
- Modify: `jevium_core/agent.py` (`final_verdict`/`final_state`, `save_failure_artifacts`)
- Modify: `jevium/cli.py` (helper, main wiring, run_plain attrs, replay drift artifacts, `import json`)
- Modify: `jevium/tui.py` (`_fail`/`_finish` wiring)
- Modify: `tests/test_agent.py`, `tests/test_cli.py`, `tests/test_tui.py`, `tests/test_chromium_live.py`
- Modify: `README.md`
- Modify: this plan file (tick every remaining checkbox)

**Interfaces:**
- Produces: `BaseBrowser.save_failure_artifacts(directory) -> list[Path]` (default `[]`); chromium override writes `trace.zip` + `network.json`; `Agent.save_failure_artifacts(directory, results_json=None) -> list[Path]` always writes `steps.jsonl` + `results.json`; CLI helper `_save_failure_artifacts(agent) -> Path | None` used on every non-zero plain-mode exit and in the outer error/interrupt handlers; TUI uses it in `_fail` and `_finish` when `exit_code != 0`; replay drift writes `drift.json` alongside browser artifacts.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agent.py`:

```python
def test_save_failure_artifacts_writes_steps_and_results(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("JEVIUM_PASSWORD", "not-a-real-secret")
    browser = runner.state["browser"]
    browser.save_failure_artifacts = Mock(return_value=[])
    runner.final_verdict = {"success": False, "reason": "url mismatch",
                            "checks": [{"type": "expected_url", "ok": False}]}
    runner.state["history"] = [{
        "step": 1, "action": "Fill Password", "kind": "fill", "text": "***",
        "url": "https://x.test/login",
        "locator": {"kind": "fill", "role": "textbox", "name": "Password",
                    "nth": 0, "secret": "password"},
    }]
    directory = tmp_path / "fail"
    saved = runner.save_failure_artifacts(directory)
    browser.save_failure_artifacts.assert_called_once_with(directory)
    steps_text = (directory / "steps.jsonl").read_text()
    assert "Fill Password" in steps_text
    assert "not-a-real-secret" not in steps_text
    results = json.loads((directory / "results.json").read_text())
    assert results["success"] is False
    assert results["reason"] == "url mismatch"
    assert {directory / "steps.jsonl", directory / "results.json"} <= set(saved)


def test_save_failure_artifacts_default_verdict(runner, tmp_path):
    runner.state["browser"].save_failure_artifacts = Mock(return_value=[])
    if hasattr(runner, "final_verdict"):
        del runner.final_verdict
    directory = tmp_path / "fail2"
    runner.save_failure_artifacts(directory)
    results = json.loads((directory / "results.json").read_text())
    assert results["success"] is None
    assert results["reason"] == "run failed before verification"
```

Append to `tests/test_cli.py`:

```python
def test_plain_failure_saves_artifacts(monkeypatch, tmp_path, capsys):
    fresh_env(monkeypatch)
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    artifact_dir = tmp_path / "art"
    instances = []

    class BlockedWithArtifacts(FakeAgent):
        def __init__(self, *args, **kwargs):
            self.record_dir = artifact_dir
            self.saved = None
            instances.append(self)

        def save_failure_artifacts(self, directory, results_json=None):
            self.saved = (directory, results_json)
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "results.json").write_text(results_json or "{}")
            return [directory / "results.json"]

        def run(self, on_waiting=None):
            yield {"status": "blocked", "elapsed_ms": 5, "history": [],
                   "page": {"url": "https://x.test/", "title": "t", "text": ""},
                   "waiting": None, "plan": ["t"]}

    monkeypatch.setattr(cli, "Agent", BlockedWithArtifacts)
    code = cli.main(["run", "--url", "https://x.test", "--task", "t", "--plain"])
    assert code == 1
    directory, results_json = instances[0].saved
    assert directory == artifact_dir
    assert json.loads(results_json)["tokens"] == {"input": 0, "output": 0}
    assert str(artifact_dir) in capsys.readouterr().err
```

Append to `tests/test_tui.py`:

```python
def test_fail_and_finish_save_artifacts(tmp_path, monkeypatch):
    from unittest.mock import Mock as _Mock
    monkeypatch.setattr(tui.verifier, "verify",
                        lambda *a, **k: {"success": None, "reason": "blocked", "checks": []})
    saved = []

    class Agent:
        record_dir = None

        def save_failure_artifacts(self, directory, results_json=None):
            saved.append(directory)
            return []

    app = tui.JeviumApp(lambda: Agent(), goals=["g"], max_steps=60)
    app.agent = Agent()
    app.run_worker = lambda *args, **kwargs: None
    app.exit = _Mock()
    blocked = {"status": "blocked", "elapsed_ms": 5, "history": [],
               "page": {"url": "https://x.test/", "title": "t", "text": ""},
               "waiting": None, "plan": ["g"]}

    async def flow():
        async with app.run_test(size=(80, 24)):
            app._finish(blocked)
            assert app.exit_code == 1
            assert saved, "_finish should save artifacts on failure"
            app._fail("boom")
            assert len(saved) == 2
            log_lines = [str(line) for line in app.query_one("#log").lines]
            assert any("failure artifacts saved to" in line for line in log_lines)

    asyncio.run(flow())
```

Append to `tests/test_chromium_live.py` (add `import json` to that file's top imports in this step):

```python
def test_failure_artifacts_include_trace(tmp_path):
    try:
        b = chromium.Browser(LOGIN_PAGE, headless=True)
    except Exception as exc:
        pytest.skip(f"chromium unavailable: {exc}")
    try:
        directory = tmp_path / "fail"
        directory.mkdir()
        b.evaluate("document.title")
        b.save_failure_artifacts(directory)
        trace = directory / "trace.zip"
        assert trace.is_file() and trace.stat().st_size > 0
        entries = json.loads((directory / "network.json").read_text())["entries"]
        assert isinstance(entries, list)
    finally:
        b.close()


def test_base_browser_artifacts_default_empty():
    from jevium_core.browser import Browser
    b = Browser.__new__(Browser)
    assert b.save_failure_artifacts(Path("/tmp/jevium-artifact-probe")) == []
```

`README.md` — after the `--wait-idle` bullet add:

```markdown
- Failure runs save `steps.jsonl`, `results.json`, and — with `--backend chromium` — `trace.zip` plus `network.json` under `runs/failure-<timestamp>/` (or the `--record` directory)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest -q tests/test_agent.py -k save_failure
uv run pytest -q tests/test_cli.py::test_plain_failure_saves_artifacts
uv run pytest -q tests/test_tui.py::test_fail_and_finish_save_artifacts
uv run pytest -q tests/test_chromium_live.py::test_failure_artifacts_include_trace tests/test_chromium_live.py::test_base_browser_artifacts_default_empty
```

Expected: FAIL — `AttributeError: 'Agent' object has no attribute 'save_failure_artifacts'`; CLI `AttributeError`/saved-not-called; TUI no save; live `AttributeError` on chromium save; base default missing method.

- [ ] **Step 3: Implement artifacts**

`jevium_core/browser.py` — add the default method to `BaseBrowser` (next to `settle`):

```python
    def save_failure_artifacts(self, directory):
        """Best-effort failure artifacts; backends without tracing return []."""
        return []
```

`jevium_core/chromium.py`:

1. Add `import json` to the top imports.
2. At the very start of `__init__` (before `sync_playwright()`), initialize:

```python
        self._network_log = []
        self._tracing = False
```

3. After the two `Emulation.*` calls and before `Page.navigate`, register the collector and start tracing:

```python
        self.page.on("response", self._record_response)
        try:
            self._context.tracing.start(screenshots=True, snapshots=True)
            self._tracing = True
        except Exception:
            self._tracing = False
```

4. Add the collector method next to `call`:

```python
    def _record_response(self, response):
        if len(self._network_log) < 500:
            self._network_log.append({
                "url": response.url,
                "status": response.status,
                "method": response.request.method,
            })
```

5. Add the save override:

```python
    def save_failure_artifacts(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        saved = []
        if self._tracing:
            try:
                self._context.tracing.stop(path=str(directory / "trace.zip"))
                saved.append(directory / "trace.zip")
            except Exception:
                pass
            self._tracing = False
        try:
            (directory / "network.json").write_text(
                json.dumps({"entries": self._network_log}, indent=2))
            saved.append(directory / "network.json")
        except OSError:
            pass
        return saved
```

6. In `close()`, stop unsaved tracing before the closer loop:

```python
        if getattr(self, "_tracing", False):
            try:
                self._context.tracing.stop()
            except Exception:
                pass
            self._tracing = False
        for closer in (
```

`jevium_core/agent.py`:

1. In `__init__`, before the `state = dict(...)` block: `self.final_verdict = None` and `self.final_state = None`.
3. `run_plain`'s signature — add the two attributes inside `jevium/cli.py`'s `run_plain`: place `agent.final_state = final` immediately after the run loop/except block (just before `if final is None:`), and `agent.final_verdict = verdict` immediately after the verdict if/else (before the summary print).
4. Add the method to `Agent`:

```python
    def save_failure_artifacts(self, directory, results_json=None):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        paths = []
        browser_paths = self.browser.save_failure_artifacts(directory)
        if browser_paths:
            paths.extend(browser_paths)
        steps_path = directory / "steps.jsonl"
        with steps_path.open("w") as fh:
            for entry in self.state.get("history") or []:
                fh.write(json.dumps(entry) + "\n")
        paths.append(steps_path)
        if results_json is None:
            verdict = getattr(self, "final_verdict", None) or {
                "success": None, "reason": "run failed before verification", "checks": []}
            results_json = json.dumps({
                "status": self.state.get("status"),
                "success": verdict.get("success"),
                "reason": verdict.get("reason"),
                "checks": verdict.get("checks") or [],
                "actions": len(self.state.get("history") or []),
                "elapsed_ms": self.state.get("elapsed_ms", 0),
                "final_url": (self.state.get("page") or {}).get("url", ""),
            }, indent=2) + "\n"
        results_path = directory / "results.json"
        results_path.write_text(results_json if results_json.endswith("\n")
                                else results_json + "\n")
        paths.append(results_path)
        return paths
```

`jevium/cli.py`:

1. Add `import json` to the top imports.
2. Add the helper before `main()`:

```python
def _save_failure_artifacts(agent):
    if agent is None or not hasattr(agent, "save_failure_artifacts"):
        return None
    directory = getattr(agent, "record_dir", None) or (
        Path("runs") / f"failure-{time.strftime('%Y%m%d-%H%M%S')}")
    results_json = None
    state = getattr(agent, "final_state", None)
    verdict = getattr(agent, "final_verdict", None) or {
        "success": None, "reason": "run failed before verification", "checks": []}
    if state is not None:
        results_json = render_report(state, verdict, "json")
    try:
        agent.save_failure_artifacts(directory, results_json=results_json)
    except Exception as exc:
        print(f"jevium: failed to save artifacts: {exc}", file=sys.stderr)
        return None
    print(f"jevium: failure artifacts saved to {directory}", file=sys.stderr)
    return directory
```

3. Restructure `main()`'s final block:

```python
    try:
        with agent:
            code = run_plain(agent, goals, max_steps=args.max_steps,
                             export_path=args.export_test, report_path=args.report,
                             start_url=args.url)
            if code != 0:
                _save_failure_artifacts(agent)
            return code
    except KeyboardInterrupt:
        print("\njevium: interrupted.", file=sys.stderr)
        _save_failure_artifacts(agent)
        return 130
    except ValueError as exc:
        print(f"jevium: {exc}", file=sys.stderr)
        _save_failure_artifacts(agent)
        return 1
```

4. Replay drift block — replace the current `except replay.ReplayDrift` body with:

```python
        except replay.ReplayDrift as exc:
            print(f"jevium: replay drifted at step {exc.index}: {exc.reason} (at {exc.url})",
                  file=sys.stderr)
            directory = Path("runs") / f"failure-{time.strftime('%Y%m%d-%H%M%S')}"
            try:
                directory.mkdir(parents=True, exist_ok=True)
                browser.save_failure_artifacts(directory)
                (directory / "drift.json").write_text(
                    json.dumps({"step": exc.index, "reason": exc.reason, "url": exc.url},
                               indent=2) + "\n")
                print(f"jevium: failure artifacts saved to {directory}", file=sys.stderr)
            except Exception as save_exc:
                print(f"jevium: failed to save replay artifacts: {save_exc}", file=sys.stderr)
            return 1
```

`jevium/tui.py`:

1. Extend the cli import: `from .cli import _save_failure_artifacts, summary_lines`
2. Add the private method:

```python
    def _save_artifacts(self) -> None:
        if self.agent is None:
            return
        directory = _save_failure_artifacts(self.agent)
        if directory is not None:
            self.query_one("#log", RichLog).write(f"failure artifacts saved to {directory}")
```

3. In `_fail`, call `self._save_artifacts()` after `self.exit_code = 1` and before `self.exit(1)`.
4. In `_finish`, set `self.agent.final_state = final` and `self.agent.final_verdict = verdict` right after the verdict if/else; after `self.exit_code = ...` add:

```python
        if self.exit_code != 0:
            self._save_artifacts()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run ruff check . && uv run pytest -q`

Expected: full suite green.

- [ ] **Step 5: Tick every checkbox in this plan, commit, push**

Tick all remaining `- [ ]` boxes in this file to `- [x]`, then:

```bash
git add jevium_core/browser.py jevium_core/chromium.py jevium_core/agent.py jevium/cli.py jevium/tui.py tests/test_agent.py tests/test_cli.py tests/test_tui.py tests/test_chromium_live.py README.md docs/superpowers/plans/2026-09-24-jevium-e2e-tier-a.md
git commit -m "feat: save failure artifacts on run errors"
git push origin main
```

Expected: push succeeds; `git status --porcelain=v1` is empty (plan file now committed, all boxes ticked).

---

### Task 7: Final verification (no commit — evidence only)

**Files:**
- Verify: everything from Tasks0–6.

**Interfaces:**
- Consumes: the pushed tree at Task 6's commit.
- Produces: fresh proof that the branch is green and in sync with the remote.

- [ ] **Step 1: Run every repository check**

Run:

```bash
set -e
uv run ruff check .
uv run pytest -q
node --check jevium_core/snapshot.js
node --check jevium_core/static/app.js
uv build
git diff --check 688c3cb..HEAD
echo "ALL CHECKS PASSED"
```

Expected: Ruff clean, all pytest tests green (previous122 + every new test from Tasks1–6), both `node --check` silent, build succeeds, no whitespace errors across the seven commits, final marker printed.

- [ ] **Step 2: Confirm secrets, cleanliness, and remote sync**

Run:

```bash
python3 -c "
from pathlib import Path
secrets = ['not-a-real-secret', '4111111111111111', 'hunter2']
allowed = {'tests/test_agent.py', 'tests/test_cli.py', 'tests/test_replay.py',
           'tests/test_export_test.py', 'tests/test_chromium_live.py'}
files = ['jevium/cli.py', 'jevium/tui.py', 'jevium/verifier.py', 'jevium/report.py',
         'jevium_core/agent.py', 'jevium_core/model.py', 'jevium_core/replay.py',
         'jevium_core/export_test.py', 'jevium_core/snapshot.js', 'README.md', '.env.example']
for f in files:
    t = Path(f).read_text()
    for s in secrets:
        assert s not in t or f in allowed, f'{s} leaked into {f}'
print('secret scan: PASS')
"
git status --porcelain=v1 | wc -l
git diff --cached --stat | wc -l
git rev-parse HEAD
git ls-remote origin refs/heads/main
git log --oneline 688c3cb..HEAD
```

Expected: `secret scan: PASS`; `0` dirty files; `0` staged lines; local HEAD SHA equals the `ls-remote` SHA; exactly seven commits listed (docs + six features).

- [ ] **Step 3: Stop — nothing to commit or push**

This task produces evidence only. The work is complete when Step1 and Step2 both match their expected outputs; report the results with the seven commit subjects and the final SHA.

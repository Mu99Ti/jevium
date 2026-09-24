# Verbose Model Traces Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `-v`/`--verbose` to `jevium run` so every Jev (`/v1/systemone`) and text-LLM (`/chat/completions`) request and response is printed to stderr, with API keys and configured secrets redacted.

**Architecture:** One trace hook inside `jevium_core/model.py::post_json` — the single choke point used by `choose()`, `field_text`, and `llm.chat_json` (planner/verifier). A module toggle `set_verbose()` is flipped by the CLI flag before the first model call; dumps go to stderr only, request once per call, every response as it arrives, retry/connection notices inline. Spec: `docs/superpowers/specs/2026-09-24-jevium-verbose-traces-design.md`.

**Tech Stack:** Python 3.12+, httpx, pytest, Ruff, Node (`node --check`), `uv`.

## Global Constraints

- Tests never call paid APIs; all responses mocked with `httpx.Response`, stderr captured with `capsys`.
- Never print the `Authorization` header or any API key; every payload dump passes `_redact_secrets` (configured `SENSITIVE_ENV` values, raw and JSON-encoded, replaced with `***`).
- Traces go to stderr only; default off; full bodies untruncated; `json.dumps(..., indent=2, ensure_ascii=False, default=str)`.
- Provider label: `jev` when `"/v1/systemone" in url`, else `llm`.
- Request traced once before the retry loop; each response traced as it arrives (including non-JSON bodies via `response.text`); retry notices `[jevium:{kind} ×] {detail}` with 1-based attempt numbers.
- Do not commit or push anything (AGENTS.md: only on user request). The task ends at a verified green, uncommitted tree (spec + plan + code + README all stay uncommitted).
- Final checks: `uv run ruff check .`, `uv run pytest -q`, `node --check jevium_core/snapshot.js`, `node --check jevium_core/static/app.js`, `uv build`, `git diff --check`.

---

### Task 1: Verbose model traces (`-v` / `--verbose`)

**Files:**
- Modify: `jevium_core/model.py` (`_VERBOSE`, `set_verbose`, trace helpers, `post_json`)
- Modify: `jevium/cli.py` (flag, import, enable call)
- Modify: `tests/test_agent.py` (6 trace tests)
- Modify: `tests/test_cli.py` (flag wiring test)
- Modify: `README.md` (synopsis + bullet)

**Interfaces:**
- Produces:
  - `model._VERBOSE: bool` (module global, default `False`)
  - `model.set_verbose(enabled: bool) -> None`
  - `model._redact_secrets(text: str) -> str`
  - `model._trace_request(kind: str, url: str, body: dict) -> None`
  - `model._trace_response(kind: str, status: int, payload: dict | str, elapsed_ms: int) -> None`
  - `model._trace_retry(kind: str, detail: str) -> None`
  - CLI: `-v` / `--verbose` on the `run` subcommand; `cli.set_verbose` is the imported symbol tests spy on.
- Consumes: existing `CLIENT.post`, `SENSITIVE_ENV`, `configured_secret`, `capsys`, `Mock`.

- [x] **Step 1: Write the failing tests**

Append to `tests/test_agent.py`, directly after `test_post_json_honors_retry_after_header` (its last line is `assert sleep.call_args_list == [call(4.0)]`):

```python
def test_verbose_traces_jev_request_and_response(monkeypatch, capsys):
    monkeypatch.setattr(model, "_VERBOSE", True)
    response = httpx.Response(200, json={
        "model": "jev-1.13.0",
        "answers": {"operation": {"choice": "CLICK",
                                  "probabilities": {"CLICK": 1.0},
                                  "confidence": 1.0}},
        "usage": {"input_tokens": 12, "output_tokens": 3},
    })
    monkeypatch.setattr(model.CLIENT, "post", Mock(return_value=response))
    out = model.post_json("https://api.typesafe.ai/v1/systemone", "sekret-api-key", {
        "state": "hello world", "model": "jev-latest",
        "questions": {"operation": {"type": "choice", "criteria": {"CLICK": "click it"}}},
    })
    assert out["model"] == "jev-1.13.0"
    err = capsys.readouterr().err
    assert "[jevium:jev →] https://api.typesafe.ai/v1/systemone" in err
    assert "[jevium:jev ←] HTTP200" in err
    assert '"hello world"' in err
    assert '"probabilities"' in err
    assert "sekret-api-key" not in err


def test_verbose_traces_llm_chat(monkeypatch, capsys):
    monkeypatch.setattr(model, "_VERBOSE", True)
    response = httpx.Response(200, json={
        "model": "deepseek-chat",
        "choices": [{"message": {"content": '{"ok":true}'}}],
    })
    monkeypatch.setattr(model.CLIENT, "post", Mock(return_value=response))
    out = model.post_json("https://api.deepseek.com/v1/chat/completions", "llm-key", {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": "split this task"}],
    })
    assert out["choices"][0]["message"]["content"] == '{"ok":true}'
    err = capsys.readouterr().err
    assert "[jevium:llm →] https://api.deepseek.com/v1/chat/completions" in err
    assert "[jevium:llm ←] HTTP200" in err
    assert '"split this task"' in err
    assert "llm-key" not in err


def test_verbose_redacts_configured_secrets(monkeypatch, capsys):
    monkeypatch.setattr(model, "_VERBOSE", True)
    monkeypatch.setenv("JEVIUM_PASSWORD", "Sup3r-Hush!")
    response = httpx.Response(200, json={
        "choices": [{"message": {"content": "typed Sup3r-Hush! now"}}],
    })
    monkeypatch.setattr(model.CLIENT, "post", Mock(return_value=response))
    model.post_json("https://api.deepseek.com/v1/chat/completions", "k", {
        "messages": [{"role": "user", "content": "type Sup3r-Hush! now"}],
    })
    err = capsys.readouterr().err
    assert "Sup3r-Hush!" not in err
    assert "***" in err


def test_verbose_off_by_default(monkeypatch, capsys):
    assert model._VERBOSE is False
    response = httpx.Response(200, json={"ok": True})
    monkeypatch.setattr(model.CLIENT, "post", Mock(return_value=response))
    model.post_json("https://api.typesafe.ai/v1/systemone", "k", {"state": "x"})
    assert "[jevium:" not in capsys.readouterr().err


def test_verbose_traces_retry(monkeypatch, capsys):
    monkeypatch.setattr(model, "_VERBOSE", True)
    monkeypatch.setattr(model.time, "sleep", lambda _seconds: None)
    limited = httpx.Response(429, json={"error": "rate limited"})
    ok = httpx.Response(200, json={"ok": True})
    monkeypatch.setattr(model.CLIENT, "post", Mock(side_effect=[limited, ok]))
    assert model.post_json("https://api.typesafe.ai/v1/systemone", "k",
                           {"state": "x"}) == {"ok": True}
    err = capsys.readouterr().err
    assert "[jevium:jev ←] HTTP429" in err
    assert '"rate limited"' in err
    assert "[jevium:jev ×] HTTP429 on attempt1; retrying" in err
    assert err.count("[jevium:jev ←] HTTP200") == 1


def test_set_verbose_toggles(monkeypatch):
    monkeypatch.setattr(model, "_VERBOSE", False)
    model.set_verbose(True)
    assert model._VERBOSE is True
    model.set_verbose(False)
    assert model._VERBOSE is False
```

Append to `tests/test_cli.py` (after `test_harness_rejects_wait_idle`):

```python
def test_verbose_flag_enables_model_trace(monkeypatch):
    fresh_env(monkeypatch)
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    spy = Mock()
    monkeypatch.setattr(cli, "set_verbose", spy)
    monkeypatch.setattr(cli, "Agent", FakeAgent)
    code = cli.main(["run", "--url", "https://x.test", "--task", "t", "--plain"])
    assert code == 0
    spy.assert_not_called()
    for flag in ("--verbose", "-v"):
        spy.reset_mock()
        code = cli.main(["run", "--url", "https://x.test", "--task", "t",
                         "--plain", flag])
        assert code == 0
        spy.assert_called_once_with(True)
```

- [x] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest -q tests/test_agent.py -k verbose -v
uv run pytest -q tests/test_cli.py::test_verbose_flag_enables_model_trace -v
```

Expected: FAIL — `AttributeError: ... has no attribute '_VERBOSE'` (monkeypatch), `AttributeError: ... has no attribute 'set_verbose'`, and `AttributeError: ... has no attribute 'set_verbose'` on `cli`.

- [x] **Step 3: Implement tracing in `jevium_core/model.py`**

1. Add `import sys` to the stdlib imports (between `re` and `time`):

```python
import json
import math
import os
import re
import sys
import time
```

2. After `CLIENT = httpx.Client(http2=True, timeout=25)` add:

```python
_VERBOSE = False


def set_verbose(enabled):
    global _VERBOSE
    _VERBOSE = bool(enabled)
```

3. Immediately before `def post_json(...)` add the helpers:

```python
def _redact_secrets(text):
    for kind in SENSITIVE_ENV:
        value = configured_secret(kind)
        if not value:
            continue
        text = text.replace(value, "***")
        text = text.replace(json.dumps(value)[1:-1], "***")
    return text


def _trace_request(kind, url, body):
    print(f"[jevium:{kind} →] {url}", file=sys.stderr)
    payload = json.dumps(body, indent=2, ensure_ascii=False, default=str)
    print(_redact_secrets(payload), file=sys.stderr)


def _trace_response(kind, status, payload, elapsed_ms):
    print(f"[jevium:{kind} ←] HTTP{status} in {elapsed_ms} ms", file=sys.stderr)
    if isinstance(payload, str):
        dump = payload
    else:
        dump = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    print(_redact_secrets(dump), file=sys.stderr)


def _trace_retry(kind, detail):
    print(f"[jevium:{kind} ×] {detail}", file=sys.stderr)
```

4. Replace the entire body of `post_json` (current body is the3-attempt loop with Retry-After handling) with:

```python
def post_json(url, key, body):
    kind = "jev" if "/v1/systemone" in url else "llm"
    if _VERBOSE:
        _trace_request(kind, url, body)
    for attempt in range(3):
        attempt_started = time.perf_counter()
        try:
            response = CLIENT.post(url, json=body, headers={"Authorization": f"Bearer {key}"})
        except httpx.HTTPError as exc:
            if _VERBOSE:
                detail = f"{type(exc).__name__} on attempt{attempt + 1}"
                if attempt < 2:
                    detail += "; retrying"
                _trace_retry(kind, detail)
            if attempt == 2:
                raise RuntimeError("Model connection failed; no action executed.") from None
            time.sleep(0.5 * 2**attempt)
            continue
        elapsed_ms = round((time.perf_counter() - attempt_started) * 1000)
        if _VERBOSE:
            try:
                payload = response.json()
            except ValueError:
                payload = response.text
            _trace_response(kind, response.status_code, payload, elapsed_ms)
        if response.status_code in {429, 529, 503} and attempt < 2:
            if _VERBOSE:
                _trace_retry(kind, f"HTTP{response.status_code} on attempt{attempt + 1}; retrying")
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
```

- [x] **Step 4: Wire the CLI flag in `jevium/cli.py`**

1. Extend the model import line to:

```python
from jevium_core.model import extract_task_credentials, set_verbose, task_contains_configured_secret
```

2. In `parse_args`, after the `--wait-idle` argument add:

```python
    run.add_argument("-v", "--verbose", action="store_true",
                     help="Print every Jev/text-model request and response to stderr.")
```

3. In `main()`, immediately after the `parse_args` try/except block (right before the `TYPESAFE_API_KEY` check) add:

```python
    if args.verbose:
        set_verbose(True)
```

- [x] **Step 5: Update `README.md`**

1. Append `[--verbose]` to the CLI synopsis (line ending with `--report`):

```markdown
  [--replay <steps.jsonl>] [--export-test <path.spec.ts>] [--report <path.json|path.xml>] [--verbose]
```

2. After the `--wait-idle` bullet add:

```markdown
- `-v`/`--verbose`: print every Jev and text-model request/response to stderr (use with `--plain`, or `2>trace.log` to capture without disturbing the TUI)
```

- [x] **Step 6: Run the tests to verify they pass**

Run:

```bash
uv run pytest -q tests/test_agent.py -k verbose -v
uv run pytest -q tests/test_cli.py::test_verbose_flag_enables_model_trace -v
```

Expected: PASS (7 tests).

- [x] **Step 7: Run the full repository checks**

Run:

```bash
set -e
uv run ruff check .
uv run pytest -q
node --check jevium_core/snapshot.js
node --check jevium_core/static/app.js
uv build
git diff --check
echo "ALL CHECKS PASSED"
```

Expected: Ruff clean, full pytest green, both node checks silent, build succeeds, no whitespace errors, final marker printed.

- [x] **Step 8: Tick this task, stop without committing**

Tick this task's checkboxes to `- [x]`. Do **not** run `git add`, `git commit`, or `git push` — the user has not requested a commit for this feature; report the verified, uncommitted change set instead (`git status --porcelain=v1` should list the spec, this plan, `jevium_core/model.py`, `jevium/cli.py`, `tests/test_agent.py`, `tests/test_cli.py`, `README.md`).

# Jevium Verbose Model Traces Design

**Date:** 2026-09-24
**Status:** Approved by the user's direct build instruction plus the standing no-questions/go-ahead directive
**Scope:** CLI verbose mode that prints every request sent to Jev (TypeSafe System One) and to the text LLM, and every response received.

## Goal

`jevium run -v` (or `--verbose`) shows the full model conversation on stderr: what `choose()` sends to `/v1/systemone` and what comes back, plus what `TYPE_TEXT`, the planner, and the verifier send to `/chat/completions` and what comes back — with credentials redacted.

## Context

Every outbound model call in the project already funnels through one function:

- `jevium_core/model.py::post_json(url, key, body)` is called by `choose()` (Jev, `POST /v1/systemone`), by `field_text` (TYPE_TEXT helper, `POST .../chat/completions`), and by `jevium/llm.py::chat_json` (planner and verifier, same chat endpoint).
- No verbose/logging path exists today; `post_json` prints nothing.

## Approaches considered

1. **Chosen: instrument `post_json` behind a module-level `set_verbose()` toggle.** One hook covers Jev + every text-LLM path with zero call-chain churn; the CLI flag flips the toggle before the planner runs, so even the first planner call is traced. Library users can call `set_verbose(True)` directly.
2. Rejected: thread a `verbose` parameter through `choose` / `field_text` / `chat_json` / planner / verifier — touches every call site, easy to miss one, larger diff for the same output.
3. Rejected: always-on structured trace files (JSONL with rotation) — heavier file lifecycle management; the user asked to *show* traces, and shell redirection (`2>trace.log`) already captures stderr when a file is wanted.

## Flag and data flow

- New `run` flag: `-v` / `--verbose` (`action="store_true"`), added after `--wait-idle`.
- `main()` sets `set_verbose(True)` immediately after argument parsing, before any model call (planner included), so plain mode, TUI mode, and replay's optional text-verifier call are all covered.
- Traces go to **stderr** only: stdout stays reserved for plain-mode lines/TUI. Pair with `--plain`, or redirect with `2>trace.log`, to avoid interleaving with the TUI screen.
- Toggle state: module global `_VERBOSE = False` in `model.py`; `set_verbose(enabled: bool) -> None` flips it. Default off; tests restore it via `monkeypatch.setattr(model, "_VERBOSE", ...)`.

## Trace format

Provider label: `jev` when `"/v1/systemone" in url`, otherwise `llm` (chat completions).

```text
[jevium:jev →] https://api.typesafe.ai/v1/systemone
{
  "model": "jev-latest",
  "state": { ... },
  "questions": { ... }
}
[jevium:jev ←] HTTP200 in 231 ms
{
  "model": "jev-1.13.0",
  "answers": { ... },
  "usage": { "input_tokens": 12, "output_tokens": 3 }
}
[jevium:llm →] https://api.deepseek.com/v1/chat/completions
{ "model": "deepseek-chat", "messages": [ ... ] }
[jevium:llm ←] HTTP200 in 410 ms
{ "model": "deepseek-chat", "choices": [ ... ] }
```

Rules:

- The **request is traced once** before the retry loop; **every response is traced** as it arrives, including error/retryable responses (a 429 body is shown before the backoff).
- Response line: `[jevium:{kind} ←] HTTP{status} in {elapsed_ms} ms` where `elapsed_ms` covers that attempt only.
- Retry/connection notices: `[jevium:{kind} ×] HTTP429 on attempt1; retrying` and `[jevium:{kind} ×] ConnectError on attempt1; retrying` (attempt is 1-based).
- Payload dumps: `json.dumps(payload, indent=2, ensure_ascii=False, default=str)`; if a response body is not JSON (e.g. an HTML error page), dump `response.text` instead.
- Full bodies, never truncated — verbose is opt-in.

## Redaction and safety

- The `Authorization` header and API keys are **never** printed; only URL + body (request) and status + body (response).
- Every dumped payload passes through `_redact_secrets(text)`, which replaces each configured `SENSITIVE_ENV` value — both raw and JSON-encoded forms — with `***`. Belt-and-braces: goals are already stripped of task credentials upstream, and snapshot secret fields already report only `""`/`"***"`.
- `ensure_ascii=False` keeps non-ASCII element labels (e.g. Persian) readable in traces.

## Error handling

- HTTP error statuses still raise the existing `RuntimeError` after their response has been traced.
- Connection errors trace the exception class name before retrying; the final failure still raises `Model connection failed; no action executed.`
- Tracing must never alter control flow: it only prints.

## Testing (offline; no paid APIs)

All in `tests/test_agent.py` (where `post_json` tests live) unless noted; responses mocked with `httpx.Response`, capture with `capsys`:

1. `test_verbose_traces_jev_request_and_response` — verbose on: request line contains the systemone URL, response line contains `HTTP200`, bodies visible (`"hello world"`, `"probabilities"`), API key absent from stderr.
2. `test_verbose_traces_llm_chat` — chat URL labeled `llm`, message content visible, key absent.
3. `test_verbose_redacts_configured_secrets` — `JEVIUM_PASSWORD` value appears in neither request nor response dumps; `***` present.
4. `test_verbose_off_by_default` — no `[jevium:` lines when the toggle is off.
5. `test_verbose_traces_retry` — 429 then 200: stderr shows the429 body, the retry notice, and exactly one `HTTP200`.
6. `test_set_verbose_toggles` — `set_verbose(True/False)` flips `_VERBOSE` (monkeypatch restores state).
7. `tests/test_cli.py::test_verbose_flag_enables_model_trace` — without the flag `set_verbose` is not called; with `--verbose` and with `-v` it is called once with `True` (spy on `cli.set_verbose`).

## Documentation

- `README.md`: add `[--verbose]` to the CLI synopsis; add bullet `- `-v`/`--verbose`: print every Jev and text-model request/response to stderr (use with `--plain`, or `2>trace.log` to capture without disturbing the TUI)`.
- No `.env` variable (flag + `set_verbose()` API only).

## Out of scope

- Rendering traces inside the TUI viewport.
- Structured/JSON trace files, trace levels/sampling, or redacting anything beyond configured secrets.
- Tracing browser/CDP traffic or screenshots.
- Changing retry/timeout behavior.

## Success criteria

- `jevium run --plain -v ...` prints paired `→`/`←` traces for every Jev and text-LLM call, including planner and verifier.
- No API key and no configured secret value ever appears in trace output.
- Default runs produce zero trace output; all repository checks pass (`ruff`, full `pytest`, both `node --check`, `uv build`, `git diff --check`).

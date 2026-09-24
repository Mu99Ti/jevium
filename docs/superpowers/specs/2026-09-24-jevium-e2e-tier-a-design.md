# Jevium E2E Tier-A Design

**Date:** 2026-09-24
**Status:** Approved by the user's "implement tier a features... no questions asked" directive
**Scope source:** Tier A of the2026-09-24 E2E feature review (replay, test export, structured verdicts, CI reports, determinism kit, failure artifacts)

## Goal

Add the six Tier-A features that turn Jevium from a task runner into a web-automation/E2E tool: deterministic replay, Playwright test export, structured verdicts, CI report output, a determinism kit, and failure artifacts — each shipped as its own TDD commit that is pushed individually.

## Global constraints

- Every feature keeps the core loop: page → indexed elements → typed operation + target → execution → verify.
- No model-generated selectors or JavaScript. Locators in recordings/exports are rendered by code from observed `role`/`name`/`data-testid` values.
- Replay and all regression paths make zero paid model calls unless a verifier text-model key is present.
- Tests never call paid APIs; fixtures use obvious fake values; no real credentials in tests.
- Browser mutations are never retried; replay aborts on the first mismatch (drift) instead of guessing.
- Each feature lands as one commit (`feat: ...` / `docs: ...` style, matching history) and is pushed immediately.
- Checks per feature: `uv run ruff check .` + `uv run pytest -q`; add `node --check jevium_core/snapshot.js` for any feature touching the snapshot; full suite + `uv build` + both node checks at the end.

## A1 — Deterministic replay (`--replay`)

### Recording contract

Every history entry written by `Agent.command("act")` gains a `locator` object, derived at execution time from the observed action (never by the model):

```json
{"kind": "fill|click|select|wait|scroll", "role": "button", "name": "Go", "nth": 0,
 "testid": "optional-data-testid", "secret": "password?", "option_value": "...?",
 "option_label": "...?", "ms": 100?, "delta": -560?}
```

- `name` is the label base (`label.split(" → ")[0]` for selects); `nth` is the index among actions sharing `(role, name, kind)` in snapshot order; `testid` is copied from the observed action when the page provides `data-testid` (snapshot emits `base.testid` only when the attribute exists).
- `wait` stores `ms` (the executor's fixed100ms); `scroll` stores `delta`; `select` stores the option value and option label; secret fills store the `secret` kind (never a value).

### Replay engine

New module `jevium_core/replay.py`:

- `load_steps(path) -> list[dict]` — reads `steps.jsonl`.
- `match_action(page, step) -> action` — when the step carries a `locator`: `testid` + kind first, then `(role, name, kind, nth)` (selects then match the option value/label among the chosen node's option actions); the legacy `choice` id is used only when no locator was recorded (old steps), because generated `eN` ids can shift when the DOM changes. No match raises `ReplayDrift(index, reason, url)`.
- `replay(browser, steps) -> {"status": "done", "history": [...], "final_page": page}` — for each step: `observe()` (fresh snapshot), match, resolve text (`history.text`, or `configured_secret(kind)` when `text == "***"`; missing env → `ReplayDrift`), then `browser.act(...)`. Rebuilds a history list compatible with the verifier/report (label, kind, text, url, locator, page_changed).

### CLI

- `run --replay STEPS.jsonl` implies plain mode (no TUI), skips the `TYPESAFE_API_KEY` requirement, planner, and the text-model warning; still requires `--task` (used as goal/test name) and `--url` (start URL).
- `--replay` + `--record` → exit2 with a clear message (replay does not record frames).
- Success = every step matched and executed → then A2-style exit via structured verdict once A2 lands (C1 exits0 after all steps, printing the final URL; C2 upgrades it with `verify(expected_url=...)`).
- `ReplayDrift` → `jevium: replay drifted at step N: <reason> (at <url>)`, exit1.
- Replay works with `--report` and `--export-test` (those features consume the rebuilt history).

## A2 — Playwright Test export (`--export-test`)

New module `jevium_core/export_test.py`:

- `render_playwright_test(*, task, start_url, history, final_page) -> str` renders a TypeScript Playwright Test file from recorded history:
  - `test(<task>, async ({ page }) => { ... })`, first line `await page.goto(<start_url>)`.
  - Locator per step: `testid` → `page.getByTestId("x")`; else `page.getByRole("<role>", { name: "<name>" })` with `.nth(n)` only when `n > 0`.
  - Actions: fill → `.fill(text)`, click → `.click()`, select → `.select_option(value)`, wait → `page.waitForTimeout(ms)`, scroll → `page.mouse.wheel({ deltaY })`.
  - Secret fills emit `process.env.<JEVIUM_VAR>` (reverse map from `SENSITIVE_ENV`) with a non-null assertion — never a literal, never `"***"`.
  - Final assertions from the final page: `await expect(page).toHaveURL("<final_url>")` and `await expect(page).toHaveTitle("<title>")`.
  - All string literals built with `json.dumps` (valid escaping).
- CLI `--export-test PATH`: after a run, export only when `status == "done"`; otherwise print `jevium: export skipped: run did not complete` to stderr and keep the original exit code. Parent directories are created. Also available after `--replay`. Wired through plain mode, replay, and TUI (`run_tui(..., export_path=...)`, rendered in `_finish`).

## A3 — Structured verifier verdicts

`verifier.verify(goals, page, history, expected_url=None)` returns:

```json
{"success": true|false|null, "reason": "...", "checks": [
  {"type": "expected_url", "ok": true, "evidence": "https://..."},
  {"type": "goal_phrase_visible", "ok": true, "optional": true, "evidence": "goal found in page text"},
  {"type": "llm_judge", "ok": true, "evidence": "<reason>"}
]}
```

Rules (in order):

1. Deterministic checks run first: `expected_url` (required, only when `expected_url` is passed — exact string match), `goal_phrase_visible` (optional, case-insensitive containment of each goal in `page["text"]`; never flips success, only adds evidence).
2. Any required check failing → `success=False` (LLM not consulted).
3. Text-model judge (`llm_judge`) runs when `TEXT_MODEL_API_KEY` exists; its verdict is required — `success = llm.ok`.
4. No LLM and no required failures: `success=True` when `expected_url` was supplied (regression semantics), else `success=None` (unchanged "unknown" behavior).
5. Existing callers keep the same defaults; replay passes `expected_url` from the last recorded step's `url`.

Existing verifier tests that assert exact dicts are updated to include `checks`.

## A4 — CI reports (`--report`)

New module `jevium/report.py`:

- `render_report(state, verdict, fmt) -> str` with `fmt` in `{"json", "xml"}` (chosen by `.json`/`.xml` suffix; any other suffix → exit2 before running).
- JSON payload: `goals, status, success, reason, checks, actions, elapsed_ms, final_url, tokens:{input,output}, text_model_calls, model_ids`.
- Token normalization sums `history[].usage` and `text_calls[].usage`, accepting TypeSafe (`input_tokens`/`output_tokens`) and OpenAI-style (`prompt_tokens`/`completion_tokens`) keys.
- JUnit XML: one testsuite `jevium`, one testcase named from the first goal (fallback `jevium run`), `time` in seconds; `success=True` → pass, `False` → `<failure message=reason>` with checks JSON as text, `None` → `<skipped/>`; `<system-out>` carries the summary lines plus checks.
- CLI `--report PATH` writes after the summary in plain mode and replay; TUI writes it in `_finish`. Parse failures/invalid suffix exit2 before any browser starts.

## A5 — Determinism kit

- `reduced_motion="reduce"` passed to both Playwright context constructors in `jevium_core/chromium.py` (launch and persistent).
- New CLI flag `--wait-idle` (chromium backend only): `chromium.Browser(..., wait_idle=False)`; `BaseBrowser.settle()` hook called at the top of `observe()`; chromium override waits `page.wait_for_load_state("networkidle", timeout=1000)` and swallows timeouts. `--backend harness --wait-idle` → exit2 alongside the existing harness restrictions.
- Test-id preference is part of A1 (snapshot emits `testid`, locators prefer it) — no change to `name()`, so the model-facing labels stay accessibility-first while replay/export get the stable handle.

## A6 — Failure artifacts

- `BaseBrowser.save_failure_artifacts(directory) -> list[Path]` default returns `[]`; chromium override: `tracing.stop(path=directory/"trace.zip")` (tracing started at browser init with screenshots+snapshots) and `network.json` from a response collector (registered once, capped at500 entries).
- `Agent.save_failure_artifacts(directory)`: mkdirs, delegates to the browser, always writes `steps.jsonl` (current history) and `results.json` (A4 JSON render of last verdict, defaulting to `{"success": null, "reason": "run failed before verification", "checks": []}`). `Agent.final_verdict` is set by `run_plain`/`_finish`.
- CLI: on any plain-mode exit ≠0 and on `ValueError`/`RuntimeError` handlers when an agent exists, save to `record_dir` if recording, else `runs/failure-<timestamp>/`; print the directory to stderr. TUI: `_fail` and `_finish` with `exit_code != 0` call the same method.
- Replay drift (A1) saves browser artifacts plus `drift.json` (`step`, `reason`, `url`).
- Harness backend: browser-level methods no-op (no Playwright tracing) — `steps.jsonl`/`results.json` still written; README documents that `trace.zip` requires `--backend chromium`.
- `chromium.close()` stops tracing without saving if still active.

## Error handling summary

| Failure | Behavior |
|---|---|
| Replay drift / unconfigured secret during replay | stderr `jevium: replay drifted...`, exit1 (+ artifacts once A6 lands) |
| `--replay --record` | exit2 before browser start |
| `--wait-idle` with harness | exit2 |
| `--report` bad suffix | exit2 before browser start |
| Export on incomplete run | stderr skip notice, original exit code preserved |
| Trace/network capture unsupported (harness) | silently skipped; steps/results still written |
| LLM verifier unavailable | verdict `None`/deterministic-only per A3 rules |

## Testing strategy (offline unless marked live)

1. **Replay:** `tests/test_replay.py` — locator recording shape (via `agent.act` on the `runner` fixture), legacy id match, testid match, role/name/nth match, select option match, drift error, secret-from-env fill, secret-missing drift, `load_steps` parsing; CLI wiring tests (`--replay` skips model key/planner, `--replay --record` exit2, drift exit1). Live: optional round-trip (record against `tests/pages/login.html`, replay it) marked `live`.
2. **Verdicts:** updated `tests/test_verifier.py` equality assertions + new cases (expected-url pass/fail short-circuits LLM, optional goal-phrase check, no-LLM+expected_url→True, no-LLM+no-expected→None).
3. **Export:** `tests/test_export_test.py` — pure string assertions (goto, role locator, nth>0, select, secret env reference, escapes quotes/newlines, URL/title asserts, no `"***"` literal anywhere).
4. **Report:** `tests/test_report.py` — JSON keys/token normalization (both usage key styles), JUnit parses via `xml.etree`, failure/skip/pass mapping, invalid suffix exit2, CLI writes file.
5. **Determinism:** CLI restriction tests; chromium `reduced_motion` and `wait_idle` wiring unit-tested by constructing nothing browser-heavy (parameter captured via monkeypatched `launch`/`new_context` where feasible); live test asserts `matchMedia("(prefers-reduced-motion: reduce)").matches`.
6. **Artifacts:** `Agent.save_failure_artifacts` with `Mock` browser (browser method called, `steps.jsonl` + `results.json` exist, secret strings absent); success path does not save; TUI/plain wiring tests with fake agents; live test asserts `trace.zip` non-empty for chromium.

## Sequencing (one commit + push per row)

| # | Commit | Contents |
|---|---|---|
|0| `docs: add E2E tier A design and plan` | this spec + implementation plan |
|1| `feat: record locator hints and replay recorded runs` | A1 (snapshot `testid`, `replay.py`, agent locator recording, CLI `--replay`, README) |
|2| `feat: return structured verifier checks` | A3 (+ replay `expected_url` wiring) |
|3| `feat: export Playwright tests from recorded runs` | A2 (`export_test.py`, CLI/TUI wiring, README) |
|4| `feat: add JUnit and JSON run reports` | A4 (`report.py`, CLI/TUI wiring, README) |
|5| `feat: add E2E determinism controls` | A5 (reduced motion, `--wait-idle`, README) |
|6| `feat: save failure artifacts on run errors` | A6 (tracing/network/agent/cli/tui, README) |

Each row is verified green (ruff + pytest + node check when snapshot touched) before its commit is pushed.

## Out of scope

- Tier-B/C features (suites, storageState, routes, flake runs, cross-browser, visual baselines, MCP mode).
- HAR capture beyond the minimal `network.json` response log.
- Model-authored test code of any kind.
- Changing gate/HITL behavior, prompts, or credentials flow.

## Success criteria

- Six features independently usable from the CLI and covered by offline tests; live tests cover snapshot testid, reduced motion, and trace.zip when Chromium is available.
- `--replay` reproduces a recorded run without any model call; drift is a clean exit1.
- `--export-test` emits a syntactically valid spec containing no secret literals.
- `--report` produces parseable JSON and JUnit XML with normalized token totals.
- Failure runs leave `steps.jsonl`, `results.json`, and (chromium) `trace.zip` + `network.json` in one directory.
- All seven commits are pushed; final tree green (`ruff`, full pytest, both node checks, `uv build`, `git diff --check`, secret scan).

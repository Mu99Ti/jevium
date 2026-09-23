# Jevium Agent-State TUI Design

**Date:** 2026-09-23
**Status:** Approved for implementation

## Goal

Make the terminal UI an agent monitor rather than a browser mirror. It should show the current agent state, the active step, completed steps, and human-intervention prompts. It must not render Playwright's browser UI, screenshots, the observed element table, or model probabilities.

## Layout

Keep the existing Textual application and these widgets in order:

1. Header
2. Meta line: status, completed-step count, and elapsed milliseconds
3. HITL banner and Resume button
4. Active-step line: the latest operation, target, and action label
5. Completed-step log
6. Footer

Remove the element-table and decision-probability widgets. The active line is a compact state summary; it is not a second history log.

## Data flow

The worker receives each `Agent.run()` snapshot and hands it to the UI thread with `call_from_thread`. The UI derives:

- meta text from `status`, `history`, and `elapsed_ms`
- active text from the latest `decision`, selected action, and observed page actions
- new completed lines from history entries not previously written

The worker remains the only code that creates and uses the synchronous Playwright agent. Resume and stop continue to call only the agent's `resume()` method. The browser remains external to the terminal UI and is not rendered inside it.

## Error and completion behavior

A factory or run failure is displayed in the log and exits with status 1. A completed run still shows the final summary and uses the existing verifier behavior. Waiting for a human remains visible with the existing banner and Resume control.

## Verification

Offline tests cover active-line formatting, no duplicate history entries, and the existing resume/stop contracts. A local TUI run supplies an agent-only terminal sample for the README. The existing pytest, Ruff, JavaScript syntax, and build checks must pass.

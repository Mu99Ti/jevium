# Jevium HITL README Design

**Date:** 2026-09-23

**Status:** Superseded for runtime behavior by `2026-09-24-jevium-element-exact-hitl-design.md`; historical documentation-only design

## Goal

Expand the existing `Human-in-the-loop` README section with both a visual demo and clearer detail about how a paused run is completed and resumed.

## Scope

### In scope

- Modify `README.md` only in the existing `Human-in-the-loop` area.
- Create a repository-relative HITL demo asset at `docs/demos/hitl.gif`.
- Convert the existing local recording:
  `/var/folders/fw/gttm4qqx3qz4799s58r64knr0000gn/T/opencode/jevium-demos/hitl.mov`
- Keep the current four pause reasons:
  - Jev chose `NEEDS_HUMAN`
  - speculative `human_intervention`
  - confidence below `JEVIUM_MIN_CONFIDENCE`
  - payment action target

### Out of scope

- No product-code, CLI, TUI, model, browser, dependency, or configuration changes.
- No new HITL gates or behavior changes.
- No credentials, API keys, or secret values in README or demo assets.
- No claims that depend only on the model returning `DONE`.

## README design

Keep the current section heading and four reasons. Add the demo immediately after the reasons, then replace the existing closing sentence with this resume flow:

1. Jevium enters `waiting_human`.
2. The person completes the step in the visible Chromium window.
3. The TUI user presses **Resume**; plain mode resumes on Enter.
4. Jevium re-observes the page and continues the loop.

The GIF caption must be factual and conservative: it may show a GitHub sign-in pause and the waiting/resume state, but it must not claim that credentials were entered or that the run succeeded unless the recording independently proves that.

## Demo asset

- Target path: `docs/demos/hitl.gif`
- Source: the local `hitl.mov` recording only.
- Before using the asset, extract representative frames and confirm they show the GitHub sign-in flow plus the Jevium/TUI waiting or Resume state.
- If the recording does not show those states, stop and report the missing evidence; do not invent a caption.
- Keep the GIF small enough for a public repository while leaving the browser and TUI recognizable.

## Verification

Run the repository checks after the README and asset are updated:

- `uv run ruff check .`
- `uv run pytest`
- `node --check jevium_core/snapshot.js`
- `node --check jevium_core/static/app.js`
- `uv build`

Also verify that:

- `README.md` references `docs/demos/hitl.gif`.
- The asset exists and is non-empty.
- The README still contains `waiting_human`, `Resume`, and the four pause reasons.
- No secrets or temporary source paths appear in the README or asset path references.

## Success criteria

- The HITL README section includes both the visual demo and a clear pause/human/resume explanation.
- The demo asset is repository-relative and evidence-backed.
- Existing HITL behavior remains unchanged.
- All repository checks pass.
- Design and implementation changes remain uncommitted until the user explicitly requests a commit.

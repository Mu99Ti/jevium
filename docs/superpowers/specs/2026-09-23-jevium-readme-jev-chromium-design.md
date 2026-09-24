# Jevium README: Jev + Chromium Design

**Date:** 2026-09-23  
**Status:** Approved design for implementation

## Goal

Rewrite `README.md` as a hybrid product story and technical reference. The opening must be memorable enough to earn attention and precise enough for browser-agent and LLM builders to trust the implementation.

The primary narrative is:

> Jev decides. Chromium acts.

The README must make the name Jevium legible as the meeting point of Jev and Chromium while keeping the actual responsibility boundaries accurate.

## Audience and voice

The first audience is developers and LLM engineers building browser agents. The voice is sharp, technical, confident, and concrete. Avoid inflated AI language, anthropomorphic claims, and unsupported reliability promises.

## Positioning

Use this hero:

> **Jevium: Jev decides. Chromium acts.**

> Give Jevium a site and a natural-language goal. It turns observed page elements into typed browser actions, executes them in real Chromium, and pauses for a person when judgment is required.

Explain the two halves without inventing a new runtime component:

- **Jev** is the TypeSafe model path. It receives an indexed page snapshot and chooses an operation, its matching target heads, and human-intervention risk. The default TypeSafe model is `jev-latest`.
- **Chromium** is the real browser execution layer that Jevium owns and drives. It executes only supported actions, rechecks freshness, and exposes the result to the next observation.
- **The boundary is the point:** Jev never emits selectors, coordinates, shell commands, or executable JavaScript. Code owns execution; the model chooses.

The copy should make Jevium feel like a reliable primitive rather than an opaque agent that can do anything.

## Proposed README structure

1. **Hero**
   - Title and positioning line.
   - One concise description of site + task input.
   - A short quickstart command.

2. **See it work**
   - Two real public-site demonstrations.
   - Normal run: Wikipedia search leading to the Gödel incompleteness article.
   - Human-in-the-loop run: GitHub sign-in leading to `waiting_human`, with no credentials entered.
   - Factual captions describing what Jev chose, what Chromium executed, and where a human takes over.

3. **Why Jevium**
   - Explain the Jev + Chromium division.
   - Highlight observed, operation-specific targets and the prohibition on model-generated selectors or executable code.
   - State that final verification is independent of the model's `DONE` choice.

4. **The Jevium loop**
   - Show the compact flow:
     `goal + page snapshot → Jev chooses operation + target → gates → execute → observe → verify`
   - Explain that a run remains small: observe, choose, act, observe.

5. **Human in the loop**
   - Describe pauses for login, CAPTCHA, payment, OTP, and low-confidence decisions.
   - Mention the TUI's `waiting_human` state and Resume control.
   - Keep the existing four gates concise rather than reproducing internal policy text.

6. **Quickstart and use Jev**
   - Keep clone, `uv sync`, Chromium installation, `.env`, and `uv run jevium run`.
   - Explain `TYPESAFE_MODEL=jev-latest` for operation/target choice.
   - Explain that `TEXT_MODEL` is used for `TYPE_TEXT`, planner, and verifier duties rather than for the Jev decision itself.

7. **CLI, environment, and development**
   - Preserve the current command shape, required and optional environment variables, and the four repository checks.
   - Do not add new dependencies or change product behavior as part of the README work.

8. **License**
   - Keep the MIT license section.

9. **Close**
   - End with:
     > Give Jevium a site and a task. Let Jev decide, Chromium act, and keep humans where judgment matters.

## Demo asset plan

The source recordings are real screen recordings produced outside the repository:

- Normal: `/var/folders/fw/gttm4qqx3qz4799s58r64knr0000gn/T/opencode/jevium-demos/normal.mov`
- HITL: `/var/folders/fw/gttm4qqx3qz4799s58r64knr0000gn/T/opencode/jevium-demos/hitl.mov`

Before referencing them, verify that each recording visibly contains the browser and the Textual TUI at the relevant moment. Convert or optimize them into committed README assets under `docs/`, using small GIFs or appropriately compressed video files that render reliably from GitHub. Do not reference the temporary `.mov` paths in the README.

The README must not claim a task was successful solely because the model returned `DONE`. Captions and claims must match the recorded run and its independent final outcome. No credentials, API keys, or other secrets may appear in recordings or copied assets.

## Copy and evidence constraints

- Use real public websites; do not add custom HTML fixtures for the demo.
- Keep README claims, raw evidence, and model-call counts consistent.
- Describe screenshots or recordings as optional evidence; the model does not consume them.
- Keep credentials server-side and mention only the minimum environment setup needed to run Jevium.
- Preserve the current MIT license and development commands.
- Do not change the CLI, TUI, model configuration, or browser implementation for this documentation task.

## Acceptance criteria

The implementation is complete when:

- `README.md` follows the approved structure and opens with the Jev + Chromium story.
- The default Jev model and the text-model division are explained accurately.
- Both demo assets are present under `docs/demos`, render from repository-relative paths, and show the claimed real scenarios.
- Human intervention, execution boundaries, and independent verification are described without overclaiming.
- The quickstart and CLI reference remain usable.
- Existing repository checks pass, and no temporary `.playwright-cli` files are included.

## Non-goals

- No product-code or dependency changes.
- No new site-specific plans, fixtures, or hardcoded field values.
- No new authentication, payment, or credential-handling behavior.
- No unverified model-call, accuracy, speed, or success-rate claims.

# Jevium HITL README Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an evidence-backed HITL demo and a clear pause/resume flow to the README without changing runtime code.

**Architecture:** This is a documentation-and-media change only. Verify the local HITL recording, convert it to the repository asset `docs/demos/hitl.gif`, and replace the existing README HITL explanation with a factual caption and four-step flow. No product code, dependencies, configuration, or runtime behavior changes.

**Tech Stack:** Markdown, ffmpeg/ffprobe, ImageMagick, Tesseract, Python standard library, `uv`, Ruff, pytest, Node.js.

## Global Constraints

- Modify only `README.md` and create `docs/demos/hitl.gif` for the implementation.
- Use only the existing local recording `/var/folders/fw/gttm4qqx3qz4799s58r64knr0000gn/T/opencode/jevium-demos/hitl.mov` as the demo source.
- Keep the existing four pause reasons in the README.
- Do not add credentials, API keys, or secret values to README or demo assets.
- Do not claim that the recording entered credentials or that the run succeeded unless independently visible in the recording.
- Do not change the CLI, TUI, browser, model, or configuration code.
- Do not delete, stage, or commit unrelated `.playwright-cli/` artifacts.
- Do not commit or push changes.
- Run the repository checks from `AGENTS.md` after the changes.

---

## File Map

- Modify: `README.md:52-61` — expand the existing `Human-in-the-loop` section.
- Create: `docs/demos/hitl.gif` — repository-relative animated HITL evidence.
- Temporary only: `/var/folders/fw/gttm4qqx3qz4799s58r64knr0000gn/T/opencode/jevium-demos/review/` — extracted review frames; never track it.
- Read only: `/var/folders/fw/gttm4qqx3qz4799s58r64knr0000gn/T/opencode/jevium-demos/hitl.mov` — source recording.

---

### Task 1: Verify the HITL recording evidence

**Files:**
- Read: `/var/folders/fw/gttm4qqx3qz4799s58r64knr0000gn/T/opencode/jevium-demos/hitl.mov`
- Create outside the repository: `/var/folders/fw/gttm4qqx3qz4799s58r64knr0000gn/T/opencode/jevium-demos/review/`

**Interfaces:**
- Consumes: the local H.264 HITL recording.
- Produces: extracted frames suitable for factual caption review and GIF conversion.

- [ ] **Step 1: Verify the source file and media properties**

Run:

```bash
ls "/var/folders/fw/gttm4qqx3qz4799s58r64knr0000gn/T/opencode/jevium-demos"
stat -f '%N %z bytes' "/var/folders/fw/gttm4qqx3qz4799s58r64knr0000gn/T/opencode/jevium-demos/hitl.mov"
ffprobe -v error \
  -show_entries format=duration,size:stream=width,height,codec_name \
  -of default=noprint_wrappers=1 \
  "/var/folders/fw/gttm4qqx3qz4799s58r64knr0000gn/T/opencode/jevium-demos/hitl.mov"
```

Expected: the file is H.264, 3024×1964, and approximately 32.30 seconds long. If the file is missing or differs materially, stop and report the evidence problem.

- [ ] **Step 2: Extract review frames**

Run:

```bash
review="/var/folders/fw/gttm4qqx3qz4799s58r64knr0000gn/T/opencode/jevium-demos/review"
mkdir -p "$review"
ffmpeg -hide_banner -y \
  -i "/var/folders/fw/gttm4qqx3qz4799s58r64knr0000gn/T/opencode/jevium-demos/hitl.mov" \
  -vf "fps=1/6" "$review/hitl-%02d.png"
```

Expected: a non-empty sequence of PNG frames is created outside the repository.

- [ ] **Step 3: Check the frames for the required visible states**

Run OCR on the extracted frames:

```bash
for frame in "/var/folders/fw/gttm4qqx3qz4799s58r64knr0000gn/T/opencode/jevium-demos/review"/hitl-*.png; do
  printf '\n--- %s ---\n' "$frame"
  tesseract "$frame" stdout 2>/dev/null
done
```

Confirm from the frames that the recording shows a GitHub sign-in flow and at least one TUI state containing `waiting_human` or the `Resume` control. Confirm that no credential entry is shown. If either required state is absent, stop and report the missing evidence; do not create a misleading caption or asset.

- [ ] **Step 4: Use only verified states in the eventual caption**

The caption must describe the visible pause and human takeover only. Do not claim that the agent completed login, entered credentials, or reached a successful final page unless the frames independently show that outcome.

---

### Task 2: Convert the verified recording into the README asset

**Files:**
- Create: `docs/demos/hitl.gif`

**Interfaces:**
- Consumes: the verified `/var/folders/fw/gttm4qqx3qz4799s58r64knr0000gn/T/opencode/jevium-demos/hitl.mov` recording.
- Produces: a non-empty animated GIF referenced by `README.md` as `docs/demos/hitl.gif`.

- [ ] **Step 1: Create the repository demo directory**

Run:

```bash
ls docs
mkdir -p docs/demos
```

Expected: `docs/demos` exists and is inside the repository.

- [ ] **Step 2: Convert the recording to a readable GIF**

Run:

```bash
ffmpeg -hide_banner -y \
  -i "/var/folders/fw/gttm4qqx3qz4799s58r64knr0000gn/T/opencode/jevium-demos/hitl.mov" \
  -vf "fps=6,scale=960:-2:flags=lanczos,split[v0][v1];[v0]palettegen=stats_mode=diff[p];[v1][p]paletteuse=dither=sierra2_4a" \
  -an -loop 0 docs/demos/hitl.gif
```

Expected: conversion completes without reading credentials or modifying product code.

- [ ] **Step 3: Validate the generated asset**

Run:

```bash
test -s docs/demos/hitl.gif
ffprobe -v error -show_entries format=duration,size \
  -of default=noprint_wrappers=1 docs/demos/hitl.gif
identify docs/demos/hitl.gif | wc -l
stat -f '%N %z bytes' docs/demos/hitl.gif
```

Expected: the asset is non-empty, animated, and recognizable at repository preview size. If its size exceeds 10485760 bytes, rerun the conversion with `fps=5,scale=800:-2` and validate again; do not compress past the point where the browser and TUI remain recognizable.

---

### Task 3: Expand the README HITL section

**Files:**
- Modify: `README.md:52-61`

**Interfaces:**
- Consumes: `docs/demos/hitl.gif` from Task 2 and the existing four pause reasons.
- Produces: one self-contained `Human-in-the-loop` section with a factual demo caption and pause/resume flow.

- [ ] **Step 1: Replace the existing section with the approved copy**

Replace the current `## Human-in-the-loop` block through the existing headed-mode sentence with this exact Markdown:

```markdown
## Human-in-the-loop

A run pauses in `waiting_human` for one of these reasons:

- **A:** Jev chose `NEEDS_HUMAN` — model-requested help (CAPTCHA, OTP, login)
- **B:** speculative `human_intervention` says a person is required
- **C:** confidence is below `JEVIUM_MIN_CONFIDENCE`
- **D:** the selected target is a payment action

![Jevium pausing at GitHub sign-in for human intervention](docs/demos/hitl.gif)

When the task reaches a login, Jevium pauses in `waiting_human` instead of guessing credentials. The visible Chromium window remains available for the person taking over.

1. Jevium enters `waiting_human`.
2. The person completes the step in the visible Chromium window.
3. The TUI shows the reason and a **Resume** button; plain mode prompts on stdin and resumes on Enter.
4. After resume, Jevium re-observes the page and continues the loop.
```

Keep the rest of the README unchanged, including the CLI, environment, development checks, and license sections.

- [ ] **Step 2: Run the README HITL contract check**

Run:

```bash
python - <<'PY'
from pathlib import Path

readme = Path("README.md").read_text()
required = [
    "## Human-in-the-loop",
    "docs/demos/hitl.gif",
    "waiting_human",
    "NEEDS_HUMAN",
    "human_intervention",
    "JEVIUM_MIN_CONFIDENCE",
    "payment action",
    "**Resume**",
]
missing = [value for value in required if value not in readme]
if missing:
    raise SystemExit(f"README missing: {missing}")
asset = Path("docs/demos/hitl.gif")
if not asset.is_file() or asset.stat().st_size == 0:
    raise SystemExit("missing demo asset: docs/demos/hitl.gif")
for forbidden in ("hitl.mov", "/var/folders"):
    if forbidden in readme:
        raise SystemExit(f"README contains temporary source reference: {forbidden}")
print("README HITL contract: PASS")
PY
```

Expected output: `README HITL contract: PASS`.

- [ ] **Step 3: Review the documentation diff**

Run:

```bash
git diff --check
git diff -- README.md
```

Read the resulting HITL section and confirm the image path, caption, four reasons, and resume flow are all present and consistent with the verified recording.

---

### Task 4: Run the full repository verification

**Files:**
- Verify: `README.md`
- Verify: `docs/demos/hitl.gif`

**Interfaces:**
- Consumes: the completed README and demo asset from Tasks 2–3.
- Produces: evidence that the documentation-only change did not break the project.

- [ ] **Step 1: Run each required repository check independently**

Run:

```bash
uv run ruff check .
uv run pytest
node --check jevium_core/snapshot.js
node --check jevium_core/static/app.js
uv build
```

Expected: Ruff reports no violations, pytest passes, both JavaScript syntax checks pass, and the package build succeeds.

- [ ] **Step 2: Check the final working tree and safety constraints**

Run:

```bash
git diff --check
git status --short
python - <<'PY'
from pathlib import Path

readme = Path("README.md").read_text()
if "hitl.mov" in readme or "/var/folders" in readme:
    raise SystemExit("temporary recording path leaked into README")
for path in ("README.md", "docs/demos/hitl.gif"):
    if not Path(path).is_file() or Path(path).stat().st_size == 0:
        raise SystemExit(f"missing or empty file: {path}")
print("HITL documentation safety check: PASS")
PY
```

Expected: no temporary recording path is in the README, the README and GIF are non-empty, and the only implementation changes are the intended README and demo asset. Leave all changes uncommitted; do not stage or push.

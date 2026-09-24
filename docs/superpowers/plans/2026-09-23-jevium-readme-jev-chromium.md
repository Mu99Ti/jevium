# Jevium README Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `README.md` as a sharp, technically credible Jevium landing page and reference, with the “Jev decides. Chromium acts.” story and repository-ready real-run demos.

**Architecture:** This is a documentation-and-evidence change only. The README will lead with the Jev + Chromium positioning, then explain the observe → choose → execute → verify loop, human intervention, setup, and the existing CLI. The two source `.mov` recordings will be converted to compact repository-local GIFs under `docs/demos/`; no product code, dependencies, or runtime behavior will change.

**Tech Stack:** Markdown, `ffmpeg`/`ffprobe`, ImageMagick, `tesseract` for footage review, `uv`, Ruff, pytest, Node syntax checks, and Hatchling via `uv build`.

## Global Constraints

- Modify `README.md` and add only the two README demo assets; do not change CLI, TUI, model configuration, browser code, or dependencies.
- Use only real public scenarios: Wikipedia and GitHub sign-in; do not add custom HTML fixtures.
- Keep `TYPESAFE_MODEL=jev-latest` as the TypeSafe/Jev decision model and explain `TEXT_MODEL` separately.
- Model output must never be described as selectors, coordinates, shell commands, or executable JavaScript.
- Do not include credentials, API keys, or secret values in the README or committed recordings.
- Keep README claims, recorded evidence, raw run evidence, and model-call counts consistent; omit unverifiable counts.
- Preserve the existing MIT license and repository checks: `uv run ruff check .`, `uv run pytest`, `node --check jevium_core/snapshot.js`, `node --check jevium_core/static/app.js`, `uv build`.
- Do not commit or push changes; the repository instruction requires explicit user authorization first.

---

## File Map

- Modify: `README.md` — replace the current flat introduction with the approved hero, demo, Jev + Chromium story, loop, HITL explanation, quickstart, and reference sections.
- Create: `docs/demos/normal.gif` — repository-local animated proof of the Wikipedia run.
- Create: `docs/demos/hitl.gif` — repository-local animated proof of the GitHub `waiting_human` pause.
- Temporary source only: `/var/folders/fw/gttm4qqx3qz4799s58r64knr0000gn/T/opencode/jevium-demos/normal.mov` and `/var/folders/fw/gttm4qqx3qz4799s58r64knr0000gn/T/opencode/jevium-demos/hitl.mov`; never reference these temporary paths from the README.
- Remove before final verification: `.playwright-cli/` — currently untracked temporary YAML files from browser inspection.

---

### Task 1: Verify the real recording evidence

**Files:**
- Read: `/var/folders/fw/gttm4qqx3qz4799s58r64knr0000gn/T/opencode/jevium-demos/normal.mov`
- Read: `/var/folders/fw/gttm4qqx3qz4799s58r64knr0000gn/T/opencode/jevium-demos/hitl.mov`
- Create outside the repository: `/var/folders/fw/gttm4qqx3qz4799s58r64knr0000gn/T/opencode/jevium-demos/review/`

**Interfaces:**
- Consumes: the two completed real-screen recordings.
- Produces: verified source recordings and representative frame paths for asset conversion.

- [ ] **Step 1: Confirm the source files and media properties**

Run:

```bash
stat -f '%N %z bytes' \
  /var/folders/fw/gttm4qqx3qz4799s58r64knr0000gn/T/opencode/jevium-demos/normal.mov \
  /var/folders/fw/gttm4qqx3qz4799s58r64knr0000gn/T/opencode/jevium-demos/hitl.mov

ffprobe -v error \
  -show_entries format=duration,size:stream=width,height,codec_name \
  -of default=noprint_wrappers=1 \
  /var/folders/fw/gttm4qqx3qz4799s58r64knr0000gn/T/opencode/jevium-demos/normal.mov

ffprobe -v error \
  -show_entries format=duration,size:stream=width,height,codec_name \
  -of default=noprint_wrappers=1 \
  /var/folders/fw/gttm4qqx3qz4799s58r64knr0000gn/T/opencode/jevium-demos/hitl.mov
```

Expected: both files are H.264, `3024x1964`; the normal recording is about `22.25` seconds and the HITL recording is about `32.30` seconds.

- [ ] **Step 2: Extract representative frames for review**

After confirming the parent directory exists with `ls /var/folders/fw/gttm4qqx3qz4799s58r64knr0000gn/T/opencode/jevium-demos`, run:

```bash
review=/var/folders/fw/gttm4qqx3qz4799s58r64knr0000gn/T/opencode/jevium-demos/review
mkdir -p "$review"

ffmpeg -hide_banner -y -i /var/folders/fw/gttm4qqx3qz4799s58r64knr0000gn/T/opencode/jevium-demos/normal.mov \
  -vf "fps=1/5" "$review/normal-%02d.png"
ffmpeg -hide_banner -y -i /var/folders/fw/gttm4qqx3qz4799s58r64knr0000gn/T/opencode/jevium-demos/hitl.mov \
  -vf "fps=1/6" "$review/hitl-%02d.png"
```

- [ ] **Step 3: Check that the normal recording shows the Wikipedia run and TUI**

Run OCR on the extracted normal frames and inspect the resulting text:

```bash
for frame in "$review"/normal-*.png; do
  printf '\n--- %s ---\n' "$frame"
  tesseract "$frame" stdout 2>/dev/null
 done
```

Confirm that the frames collectively show the browser navigating to the Gödel article and the Jevium/TUI state. Do not use the raw OCR as proof of exact action text if it is unreadable; use it only to locate the relevant visual moments.

- [ ] **Step 4: Check that the HITL recording shows the human gate and TUI**

Run:

```bash
for frame in "$review"/hitl-*.png; do
  printf '\n--- %s ---\n' "$frame"
  tesseract "$frame" stdout 2>/dev/null
 done
```

Confirm that the frames collectively show GitHub sign-in and the TUI `waiting_human`/Resume state, with no credential entry. If either recording fails this check, do not create a misleading caption or asset; report the missing visual evidence before proceeding.

- [ ] **Step 5: Record the evidence result**

Keep a short list of the timestamps that prove the browser and TUI claims. The list is used only to choose factual README captions; do not add unverifiable model-call counts or success claims.

---

### Task 2: Convert the verified recordings into README assets

**Files:**
- Create: `docs/demos/normal.gif`
- Create: `docs/demos/hitl.gif`

**Interfaces:**
- Consumes: the two verified source `.mov` files from Task 1.
- Produces: small, repository-relative animated assets referenced by `README.md`.

- [ ] **Step 1: Verify the target parent and create the demo directory**

Run:

```bash
ls docs
mkdir -p docs/demos
```

- [ ] **Step 2: Convert the normal run to a readable GIF**

Run:

```bash
ffmpeg -hide_banner -y \
  -i /var/folders/fw/gttm4qqx3qz4799s58r64knr0000gn/T/opencode/jevium-demos/normal.mov \
  -vf "fps=6,scale=960:-2:flags=lanczos,split[v0][v1];[v0]palettegen=stats_mode=diff[p];[v1][p]paletteuse=dither=sierra2_4a" \
  -an -loop 0 docs/demos/normal.gif
```

- [ ] **Step 3: Convert the HITL run to a readable GIF**

Run:

```bash
ffmpeg -hide_banner -y \
  -i /var/folders/fw/gttm4qqx3qz4799s58r64knr0000gn/T/opencode/jevium-demos/hitl.mov \
  -vf "fps=6,scale=960:-2:flags=lanczos,split[v0][v1];[v0]palettegen=stats_mode=diff[p];[v1][p]paletteuse=dither=sierra2_4a" \
  -an -loop 0 docs/demos/hitl.gif
```

- [ ] **Step 4: Validate both assets before referencing them**

Run:

```bash
for asset in docs/demos/normal.gif docs/demos/hitl.gif; do
  test -s "$asset"
  ffprobe -v error -show_entries format=duration,size \
    -of default=noprint_wrappers=1 "$asset"
  magick identify "$asset" | wc -l
  stat -f '%N %z bytes' "$asset"
done
```

Expected: both files exist, are non-empty animated images, and remain small enough to commit for a public repository. If either asset is unreadably large, rerun only that conversion with `scale=800:-2` and `fps=5`; do not compress it until the browser and TUI are still recognizable.

---

### Task 3: Rewrite the README around Jev + Chromium

**Files:**
- Modify: `README.md:1-110`
- Reference: `docs/tui-sample.png`
- Reference: `docs/demos/normal.gif`
- Reference: `docs/demos/hitl.gif`

**Interfaces:**
- Consumes: the two validated assets from Task 2 and the existing `.env.example`, CLI, TUI, and development commands.
- Produces: one self-contained public README that explains the product, model split, safety boundary, and usage.

- [ ] **Step 1: Replace the opening with the approved hero**

The first section must contain these exact ideas and wording:

```markdown
# Jevium: Jev decides. Chromium acts.

Give Jevium a site and a natural-language goal. It turns observed page elements into typed browser actions, executes them in real Chromium, and pauses for a person when judgment is required.
```

Immediately explain:

- Jev is the TypeSafe model path, with `jev-latest` as the default.
- Chromium is the real browser execution layer that Jevium owns and drives.
- Jev chooses; code owns execution.
- The model never emits selectors, coordinates, shell commands, or executable JavaScript.

Keep this sharp and technically confident; do not use claims such as “fully autonomous,” “never makes mistakes,” or “works on every website.”

- [ ] **Step 2: Add the real demo section**

Add the following relative image references and factual captions:

```markdown
## See it work

### Normal run

![Jevium running a real Wikipedia search and opening the Gödel article](docs/demos/normal.gif)

Jev chooses the search and article targets; Chromium executes the actions and the run is independently verified.

### Human in the loop

![Jevium pausing at GitHub sign-in for human intervention](docs/demos/hitl.gif)

When the task reaches a login, Jevium enters `waiting_human` instead of guessing credentials. The visible browser remains available for the person taking over.
```

If the recorded run does not support a more specific final outcome, use the conservative wording “the run reaches the recorded state” rather than claiming a verified success.

- [ ] **Step 3: Add the Jevium loop and trust explanation**

Include this compact flow:

```text
goal + page snapshot
        │
        ▼
Jev chooses operation + target
        │
        ▼
gates ──► execute ──► observe ──► verify
```

Explain in plain English that targets are observed elements, operation-specific target heads are consumed, mutations are freshness-checked, and final verification is independent of the model’s `DONE` choice. Do not reintroduce site-specific plans, hardcoded values, or model-generated selectors.

- [ ] **Step 4: Preserve the human-in-the-loop and practical reference sections**

Keep these sections and facts, rewritten for flow rather than removed:

- `waiting_human` for model-requested help, speculative intervention, low confidence, and payment actions.
- `Resume` in the TUI and the visible browser as the intervention surface.
- Clone, `uv sync`, `uv run playwright install chromium`, `.env`, and `uv run jevium run` quickstart.
- The current `jevium run` CLI flags and exit codes.
- `TYPESAFE_API_KEY`, `TYPESAFE_MODEL=jev-latest`, `TEXT_MODEL_API_KEY`, `TEXT_MODEL`, optional base URLs, reasoning, planner, and confidence settings.
- The existing Ruff, pytest, JavaScript syntax, and build checks.
- MIT license.

- [ ] **Step 5: Add the closing line**

End the README before the license with:

```markdown
Give Jevium a site and a task. Let Jev decide, Chromium act, and keep humans where judgment matters.
```

- [ ] **Step 6: Run the documentation contract check**

Run this stdlib-only check:

```bash
python - <<'PY'
from pathlib import Path

readme = Path("README.md").read_text()
required = [
    "# Jevium: Jev decides. Chromium acts.",
    "TYPESAFE_MODEL=jev-latest",
    "docs/demos/normal.gif",
    "docs/demos/hitl.gif",
    "waiting_human",
    "not executable code",
    "uv run pytest",
    "MIT",
]
missing = [value for value in required if value not in readme]
if missing:
    raise SystemExit(f"README missing: {missing}")
for asset in ("docs/demos/normal.gif", "docs/demos/hitl.gif"):
    if not Path(asset).is_file() or Path(asset).stat().st_size == 0:
        raise SystemExit(f"missing demo asset: {asset}")
print("README contract: PASS")
PY
```

- [ ] **Step 7: Check Markdown and diff hygiene**

Run:

```bash
git diff --check
git diff --stat -- README.md docs/demos
```

Do not commit; leave the changes for user review.

---

### Task 4: Clean temporary files and run the full verification suite

**Files:**
- Remove: `.playwright-cli/`
- Verify: all modified documentation and demo assets.

**Interfaces:**
- Consumes: completed README and demo assets from Tasks 2–3.
- Produces: a clean working tree containing only intended documentation changes and passing project checks.

- [ ] **Step 1: Confirm the temporary directory contains only browser-inspection artifacts**

Run:

```bash
find .playwright-cli -maxdepth 2 -type f -print
```

Expected: only the two untracked YAML page snapshots already observed. Do not remove any tracked project file.

- [ ] **Step 2: Remove the temporary browser-inspection directory**

Run:

```bash
rm -rf .playwright-cli
```

- [ ] **Step 3: Run the repository’s required checks**

Run each command independently so failures are attributable:

```bash
uv run ruff check .
uv run pytest
node --check jevium_core/snapshot.js
node --check jevium_core/static/app.js
uv build
```

Expected: Ruff reports no violations, all tests pass, both JavaScript files pass syntax checks, and the package build succeeds.

- [ ] **Step 4: Review the final uncommitted diff and secret safety**

Run:

```bash
git status --short
git diff --check
git diff -- README.md
rg -n 'sk-[A-Za-z0-9]|api[_-]?key[[:space:]]*=' README.md docs/demos || true
```

Confirm that the diff contains only `README.md`, the design/plan documents already created, and the two intended demo assets; no `.env`, credential, or temporary `.playwright-cli` file is included. Do not commit or push.

- [ ] **Step 5: Report completion with evidence**

Record the exact check results, demo asset sizes, and the final `git status --short`. The completion claim must be based on those outputs, not on a successful model `DONE` response.

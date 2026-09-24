# Jevium: Jev decides. Chromium acts.

Give Jevium a site and a natural-language goal. It turns observed page elements into typed browser actions, executes them in real Chromium, and pauses for a person when judgment is required.

## Jev + Chromium

Jevium is the meeting point of **Jev + Chromium**.

- **Jev** is the TypeSafe model path. The default model is `jev-latest`. Jev receives an indexed page snapshot and chooses an operation, its matching target heads, and human-intervention risk. Jev chooses; code owns execution.
- Jev never emits selectors, coordinates, shell commands, or executable JavaScript.
- **Chromium** is the real browser execution layer that Jevium owns and drives — self-managed, visible by default with headless optional, not a remote sandbox.
- Field text for `TYPE_TEXT`, plus planner and verifier duties, uses the separate text model; Jev is the decision model.

## The Jevium loop

```text
goal + page snapshot
        │
        ▼
Jev chooses operation + target
        │
        ▼
gates ──► execute ──► observe ──► verify
```

Targets are observed elements from the indexed snapshot, never strings the model invents. One Jev request returns an operation plus its operation-specific target heads, and only the selected operation's target is consumed.

Every mutation is freshness-checked against the current page before it runs. Final verification inspects the real page outcome independently of the model's `DONE` choice.

Model output is not executable code: no site-specific plans, no hardcoded field values, no model-generated selectors.

## Quickstart

```bash
git clone https://github.com/Mu99Ti/jevium.git
cd jevium
uv sync
uv run playwright install chromium
cp .env.example .env
# Add TYPESAFE_API_KEY. Add TEXT_MODEL_API_KEY for TYPE_TEXT, planner, and verifier.
uv run jevium run --url https://example.com --task 'Open the More information link'
```

Plain line logs instead of the TUI:

```bash
uv run jevium run --plain \
  --url https://en.wikipedia.org/wiki/Main_Page \
  --task "Find and open the Wikipedia article about Gödel's incompleteness theorems."
```

## Human-in-the-loop

A run pauses in `waiting_human` only when the next step needs a person:

- **A:** a CAPTCHA or human-verification challenge is present
- **B:** the selected target is a one-time code (OTP/2FA) field
- **C:** the selected target is a payment confirmation click
- **D:** an empty login/payment field has no configured value
- **E:** Jev chose `NEEDS_HUMAN` for a barrier outside those cases
- **F:** speculative `human_intervention` or confidence below `JEVIUM_MIN_CONFIDENCE` (safety pauses)

Each pause names the exact element when the barrier is an observed target.

Configure login and card values in git-ignored `.env` (`JEVIUM_USERNAME`, `JEVIUM_PASSWORD`, optional `JEVIUM_CARD_*`). Jevium fills those observed fields itself and never sends the values to a model. A login without a CAPTCHA proceeds automatically; the final payment click still pauses for a person.

1. Jevium enters `waiting_human` and shows the exact element and reason.
2. The person completes that step in the visible Chromium window.
3. The TUI shows the reason and a **Done — resume** button; plain mode prompts on stdin and resumes on Enter.
4. After marking the step done, Jevium re-checks the page and continues. If the page does not settle, it returns to `waiting_human` with a clear reason.

## CLI

```bash
jevium run --url <URL> --task '<goal>' \
  [--plain] [--headless] [--profile <name>] [--record] \
  [--backend chromium|harness] [--max-steps N]
```

- `--plain`: line logs instead of the TUI
- `--headless`: headed is the default so a human can intervene
- `--profile <name>`: persistent Chromium profile under `~/.jevium/profiles/`
- `--record`: save screenshots and `steps.jsonl` under `runs/<timestamp>/`
- `--backend chromium|harness`: default is self-managed Chromium
- `--max-steps N`: browser mutation budget; default comes from the agent
- `--replay <steps.jsonl>`: replay a recorded run deterministically, without model calls
- `--export-test <path.spec.ts>`: write a deterministic Playwright Test from a completed run or replay

Exit codes: `0` done, `1` blocked or failed, `2` usage/config error, `130` interrupt.

## Environment

```bash
cp .env.example .env
```

Required:

- `TYPESAFE_API_KEY`
- `TEXT_MODEL_API_KEY` for `TYPE_TEXT`, planner, and verifier

Defaults and optional overrides:

- `TYPESAFE_MODEL=jev-latest`
- `TYPESAFE_BASE_URL`
- `TEXT_MODEL_BASE_URL`
- `TEXT_MODEL`
- `TEXT_MODEL_REASONING`
- `PLANNER_MODEL`
- `JEVIUM_MIN_CONFIDENCE`

Optional login/payment secrets (server-side only; never put them in `--task`):

- `JEVIUM_USERNAME`
- `JEVIUM_PASSWORD`
- `JEVIUM_CARD_NUMBER`
- `JEVIUM_CARD_EXPIRY`
- `JEVIUM_CARD_CVV`
- `JEVIUM_CARD_NAME`

Secret values stay in your local git-ignored `.env`. Jevium injects them only into observed secret fields and never sends them to models, history, or logs.

## Development

```bash
uv run ruff check .
uv run pytest -q
node --check jevium_core/snapshot.js
node --check jevium_core/static/app.js
uv build
```

Give Jevium a site and a task. Let Jev decide, Chromium act, and keep humans where judgment matters.

## License

MIT. See [`LICENSE`](LICENSE).

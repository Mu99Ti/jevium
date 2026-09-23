"""Live inspector for a jevium run: agent state, active step, log, and HITL banner."""

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, RichLog, Static

from . import verifier
from .cli import summary_lines

_STATUS_LABELS = {
    "ready": "READY",
    "idle": "IDLE",
    "predicted": "RUNNING",
    "waiting_human": "HUMAN ACTION",
    "done": "COMPLETE",
    "blocked": "BLOCKED",
    "error": "ERROR",
}
_STATUS_CLASSES = (
    "status-ready",
    "status-running",
    "status-waiting",
    "status-done",
    "status-error",
)


def _status_label(state):
    status = str(state.get("status") or "ready").lower()
    return _STATUS_LABELS.get(status, status.replace("_", " ").upper())


def _status_class(state):
    status = str(state.get("status") or "ready").lower()
    if status == "waiting_human":
        return "status-waiting"
    if status == "done":
        return "status-done"
    if status in {"blocked", "error"}:
        return "status-error"
    if status in {"ready", "idle"}:
        return "status-ready"
    return "status-running"


def _set_status_class(widget, state):
    for class_name in _STATUS_CLASSES:
        widget.remove_class(class_name)
    widget.add_class(_status_class(state))


def _goal_text(state, goals):
    plan = state.get("plan")
    if plan is None:
        plan = goals
    if isinstance(plan, str):
        return plan.strip() or "No goal provided"
    parts = [str(goal).strip() for goal in plan or []]
    return " · ".join(part for part in parts if part) or "No goal provided"


def _page_text(state):
    page = state.get("page") or {}
    title = str(page.get("title") or "").strip()
    url = str(page.get("url") or "").strip()
    if title and url and url not in title:
        return f"{title} · {url}"
    return title or url or "Opening page…"


def _format_elapsed(elapsed_ms):
    elapsed_ms = int(elapsed_ms or 0)
    if elapsed_ms < 1000:
        return f"{elapsed_ms} ms"
    return f"{elapsed_ms / 1000:.1f} s"


def _action_count_text(count):
    return f"{count} action" if count == 1 else f"{count} actions"


def _active_line(state):
    waiting = state.get("waiting")
    if state.get("status") == "waiting_human" and waiting:
        return f"Human action: {waiting.get('reason', 'human action required')}"
    decision = state.get("decision")
    if decision:
        target = decision.get("target")
        label = ""
        for element in state.get("elements") or []:
            if element.get("index") == target:
                label = element.get("label", "")
                break
        if not label:
            for action in (state.get("page") or {}).get("actions") or []:
                if action.get("id") == decision.get("choice"):
                    label = action.get("label", "")
                    break
        operation = decision.get("operation", "?")
        if label and target:
            return f"Next step: {operation} — {label} [{target}]"
        if label:
            return f"Next step: {operation} — {label}"
        if target:
            return f"Next step: {operation} [{target}]"
        return f"Next step: {operation}"
    history = state.get("history") or []
    if history:
        last = history[-1]
        return f"Last action: {last.get('kind', '?')} {last.get('action', '')}"
    return f"State: {state.get('status', 'idle')}"


def _history_lines(history, seen):
    lines = []
    for entry in history[seen:]:
        lines.append(
            f"{entry.get('step')}: {entry.get('kind')} {entry.get('action')}"
            + (f" → {entry.get('text')}" if entry.get("text") else "")
        )
    return lines


class JeviumApp(App):
    CSS = """
    Screen {
      background: $background;
    }
    #meta {
      height: 6;
      margin: 0 2;
    }
    #status-card {
      width: 1fr;
      height: 100%;
      padding: 0 2;
      background: $panel;
      border: round $panel-lighten-2;
    }
    #goal-card {
      width: 2fr;
      height: 100%;
      padding: 0 2;
      margin-left: 1;
      background: $panel;
      border: round $panel-lighten-2;
    }
    #metrics {
      width: 2fr;
      height: 100%;
      padding: 0 2;
      margin-left: 1;
      background: $panel;
      border: round $panel-lighten-2;
    }
    #metrics-row {
      height: 1;
    }
    #steps {
      width: 1fr;
      color: $text-muted;
    }
    #elapsed {
      width: 1fr;
      color: $text-muted;
      text-align: right;
    }
    #page {
      height: 1;
      margin-top: 0;
      color: $text-muted;
      text-overflow: ellipsis;
      text-wrap: nowrap;
    }
    #active-card {
      height: 4;
      margin-top: 1;
      padding: 0 2;
      background: $panel;
      border-left: thick $primary;
    }
    #active-card .eyebrow {
      color: $primary;
    }
    #active {
      height: 1;
      margin-top: 0;
      color: $text;
      text-overflow: ellipsis;
      text-wrap: nowrap;
    }
    #banner {
      display: none;
      height: 5;
      margin-top: 1;
      padding: 0 2;
      background: $panel;
      border: round $warning;
    }
    #banner.visible {
      display: block;
    }
    #banner-header {
      height: 1;
      align: left middle;
    }
    #banner-title {
      width: 1fr;
      color: $warning;
      text-style: bold;
    }
    #banner-message {
      height: 2;
      margin-top: 0;
      text-overflow: ellipsis;
      text-wrap: nowrap;
    }
    #resume {
      width: 16;
      min-width: 16;
      height: 1;
      margin-left: 1;
    }
    #activity-title {
      height: 1;
      margin: 0 2;
      color: $text-muted;
      text-style: bold;
    }
    #log {
      height: 1fr;
      margin: 0 2;
      border: round $panel-lighten-2;
      padding: 0 1;
    }
    #status {
      width: auto;
      height: 1;
      margin-top: 1;
      padding: 0 1;
      color: $text;
    }
    .eyebrow {
      color: $text-muted;
      text-style: bold;
    }
    .goal-text {
      margin-top: 0;
      color: $text;
    }
    #goal {
      height: 1;
      text-overflow: ellipsis;
      text-wrap: nowrap;
    }
    .status-ready {
      color: $text-muted;
    }
    .status-running {
      color: $success;
      text-style: bold;
    }
    .status-waiting {
      color: $warning;
      text-style: bold;
    }
    .status-done {
      color: $success;
      text-style: bold;
    }
    .status-error {
      color: $error;
      text-style: bold;
    }
    Footer {
      background: $panel;
    }
    """

    def __init__(self, agent_factory, *, goals, max_steps=None):
        super().__init__()
        self.agent_factory = agent_factory
        self.agent = None
        self.goals = goals
        self.max_steps = max_steps or 60
        self.exit_code = 1
        self._stopped = False
        self._logged_steps = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="meta"):
            with Vertical(id="status-card"):
                yield Static("STATUS", classes="eyebrow")
                yield Static(
                    "READY",
                    id="status",
                    classes="status-ready",
                    markup=False,
                )
            with Vertical(id="goal-card"):
                yield Static("GOAL", classes="eyebrow")
                yield Static(
                    _goal_text({}, self.goals),
                    id="goal",
                    classes="goal-text",
                    markup=False,
                )
            with Vertical(id="metrics"):
                with Horizontal(id="metrics-row"):
                    yield Static(
                        "0 actions",
                        id="steps",
                        markup=False,
                    )
                    yield Static("0 ms", id="elapsed", markup=False)
                yield Static("Opening page…", id="page", markup=False)
        with Vertical(id="active-card"):
            yield Static("CURRENT STEP", classes="eyebrow")
            yield Static(
                "Ready to begin",
                id="active",
                markup=False,
            )
        with Vertical(id="banner"):
            with Horizontal(id="banner-header"):
                yield Static(
                    "HUMAN ACTION REQUIRED",
                    id="banner-title",
                    markup=False,
                )
                yield Button(
                    "Resume run",
                    id="resume",
                    variant="primary",
                    compact=True,
                    tooltip="Continue after completing the browser step",
                )
            yield Static(
                "",
                id="banner-message",
                markup=False,
            )
        yield Static("ACTIVITY", id="activity-title", classes="eyebrow")
        yield RichLog(highlight=True, wrap=True, id="log")
        yield Footer(compact=True)

    def on_mount(self) -> None:
        self.title = "Jevium"
        self.sub_title = "Browser agent monitor"
        self.query_one("#banner", Vertical).remove_class("visible")
        self.query_one("#resume", Button).display = False
        self.run_worker(self._drive, thread=True)

    def _request_stop(self) -> None:
        """Unblock the worker on quit; safe from any thread."""
        self._stopped = True
        if self.agent is not None:
            self.agent.resume()

    def on_unmount(self) -> None:
        self._request_stop()

    def _drive(self) -> None:
        """Agent loop: worker thread; blocks on the resume Event while waiting."""
        final = None
        try:
            with self.agent_factory() as agent:
                self.agent = agent
                for state in agent.run():
                    if self._stopped:
                        return
                    final = state
                    self.call_from_thread(self._render, state)
        except Exception as exc:
            if not self._stopped:
                self.call_from_thread(self._fail, str(exc))
            return
        if not self._stopped:
            self.call_from_thread(self._finish, final)

    def _render(self, state) -> None:
        history = state.get("history") or []
        status = self.query_one("#status", Static)
        status.update(_status_label(state))
        _set_status_class(status, state)
        self.query_one("#goal", Static).update(_goal_text(state, self.goals))
        self.query_one("#steps", Static).update(_action_count_text(len(history)))
        self.query_one("#elapsed", Static).update(_format_elapsed(state.get("elapsed_ms")))
        self.query_one("#page", Static).update(_page_text(state))
        self.query_one("#active", Static).update(_active_line(state))
        log = self.query_one("#log", RichLog)
        for line in _history_lines(history, self._logged_steps):
            log.write(line)
        self._logged_steps = len(history)

        waiting = state.get("waiting")
        banner = self.query_one("#banner", Vertical)
        resume = self.query_one("#resume", Button)
        if state.get("status") == "waiting_human" and waiting:
            reason = waiting.get("reason", "human action required")
            self.query_one("#banner-message", Static).update(
                f"{reason}\nComplete the step in the browser window, then resume Jevium."
            )
            banner.add_class("visible")
            resume.display = True
            resume.focus()
        else:
            banner.remove_class("visible")
            resume.display = False

    def handle_resume(self) -> None:
        """Thread-safe: only signals the worker; never touches Playwright here."""
        if self.agent is not None:
            self.agent.resume()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "resume":
            self.handle_resume()
            self.query_one("#banner", Vertical).remove_class("visible")
            event.button.display = False

    def _fail(self, message: str) -> None:
        status = self.query_one("#status", Static)
        status.update("ERROR")
        _set_status_class(status, {"status": "error"})
        self.query_one("#active", Static).update(f"Error: {message}")
        self.query_one("#log", RichLog).write(f"jevium: {message}")
        self.exit_code = 1
        self.exit(1)

    def _finish(self, state) -> None:
        final = state or self.agent.state
        if final.get("status") == "done":
            verdict = verifier.verify(
                self.goals,
                final.get("page") or {},
                final.get("history") or [],
            )
        else:
            verdict = {
                "success": None,
                "reason": f"run ended {final.get('status')}; not verified.",
            }
        log = self.query_one("#log", RichLog)
        log.write("--- summary ---")
        for line in summary_lines(final, verdict):
            log.write(line)
        self.exit_code = 0 if final.get("status") == "done" else 1
        self.exit(self.exit_code)


def run_tui(agent_factory, *, goals, max_steps=None) -> int:
    app = JeviumApp(agent_factory, goals=goals, max_steps=max_steps)
    result = app.run()
    return int(result) if isinstance(result, int) else app.exit_code

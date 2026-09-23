"""Live inspector for a jevium run: agent state, active step, log, and HITL banner."""

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Footer, Header, RichLog, Static

from . import verifier
from .cli import summary_lines


def _active_line(state):
    waiting = state.get("waiting")
    if state.get("status") == "waiting_human" and waiting:
        return f"waiting: {waiting.get('reason', 'human action required')}"
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
        suffix = f" [{target}] {label}" if target else (f" {label}" if label else "")
        return f"running: {decision.get('operation', '?')}{suffix}"
    history = state.get("history") or []
    if history:
        last = history[-1]
        return f"last: {last.get('kind', '?')} {last.get('action', '')}"
    return f"state: {state.get('status', 'idle')}"


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
    #banner { display: none; height: auto; background: $panel; color: $text; padding: 1 2; }
    #banner.visible { display: block; }
    #meta { height: 3; padding: 0 1; }
    #active { height: 3; padding: 0 1; }
    #log { height: 1fr; border: round $secondary; }
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
        yield Static("", id="meta")
        yield Static("", id="banner")
        with Horizontal():
            yield Button("Resume", id="resume", variant="error")
        yield Static("state: ready", id="active")
        yield RichLog(highlight=True, wrap=True, id="log")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "jevium"
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
                for state in agent.run():          # on_waiting=None -> Event block
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
        self.query_one("#meta", Static).update(
            f"{state.get('status')} · {len(history)}/{self.max_steps} steps · "
            f"{state.get('elapsed_ms', 0)} ms"
        )
        self.query_one("#active", Static).update(_active_line(state))
        log = self.query_one("#log", RichLog)
        for line in _history_lines(history, self._logged_steps):
            log.write(line)
        self._logged_steps = len(history)
        waiting = state.get("waiting")
        banner = self.query_one("#banner", Static)
        resume = self.query_one("#resume", Button)
        if state.get("status") == "waiting_human" and waiting:
            banner.update(
                f"WAITING FOR HUMAN — {waiting.get('reason', '')}\n"
                "Finish the step in the browser window, then press Resume."
            )
            banner.add_class("visible")
            resume.display = True
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
            self.query_one("#banner", Static).remove_class("visible")
            event.button.display = False

    def _fail(self, message: str) -> None:
        self.query_one("#log", RichLog).write(f"jevium: {message}")
        self.exit_code = 1
        self.exit(1)

    def _finish(self, state) -> None:
        final = state or self.agent.state
        if final.get("status") == "done":
            verdict = verifier.verify(self.goals, final.get("page") or {}, final.get("history") or [])
        else:
            verdict = {"success": None, "reason": f"run ended {final.get('status')}; not verified."}
        log = self.query_one("#log", RichLog)
        log.write("--- summary ---")
        for line in summary_lines(final, verdict, max_steps=self.max_steps):
            log.write(line)
        self.exit_code = 0 if final.get("status") == "done" else 1
        self.exit(self.exit_code)


def run_tui(agent_factory, *, goals, max_steps=None) -> int:
    app = JeviumApp(agent_factory, goals=goals, max_steps=max_steps)
    result = app.run()
    return int(result) if isinstance(result, int) else app.exit_code

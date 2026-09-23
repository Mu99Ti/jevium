"""TUI helpers and resume wiring. No event loop, no browser."""

import asyncio
import threading

from jevium import tui


def _collect_ids(widget):
    ids = set()
    if widget.id:
        ids.add(widget.id)
    for child in widget.children:
        ids.update(_collect_ids(child))
    return ids


def test_compose_shows_agent_state_only():
    app = tui.JeviumApp(lambda: None, goals=["g"], max_steps=60)
    app.run_worker = lambda *args, **kwargs: None

    async def collect_ids():
        async with app.run_test(size=(80, 24)):
            ids = set()
            for widget in app.screen.children:
                ids.update(_collect_ids(widget))
            return ids

    ids = asyncio.run(collect_ids())
    assert {"meta", "banner", "resume", "active", "log"} <= ids
    assert "elements" not in ids
    assert "decision" not in ids


def test_active_line_reports_running_step():
    state = {
        "status": "predicted",
        "decision": {"operation": "CLICK", "target": "7", "choice": "e7"},
        "elements": [{"index": "7", "label": "Open article"}],
        "page": {"actions": []},
        "history": [],
    }
    assert tui._active_line(state) == "running: CLICK [7] Open article"


def test_active_line_reports_waiting_human():
    state = {
        "status": "waiting_human",
        "decision": None,
        "waiting": {"reason": "Payment confirmation"},
        "elements": [],
        "page": {"actions": []},
        "history": [],
    }
    assert tui._active_line(state) == "waiting: Payment confirmation"


def test_history_lines_write_each_entry_once():
    history = [
        {"step": 1, "kind": "click", "action": "Open article"},
        {"step": 2, "kind": "type", "action": "Search", "text": "godel"},
    ]
    first = tui._history_lines(history, 0)
    assert first == [
        "1: click Open article",
        "2: type Search → godel",
    ]
    assert tui._history_lines(history, len(first)) == []


def test_drive_creates_agent_in_worker_thread():
    built = []

    class FakeAgent:
        def run(self, on_waiting=None):
            return iter(())

        def resume(self):
            pass

        def close(self):
            pass

    def factory():
        built.append(threading.get_ident())
        return FakeAgent()

    app = tui.JeviumApp(factory, goals=["g"], max_steps=1)
    app.call_from_thread = lambda *args, **kwargs: None
    worker = threading.Thread(target=app._drive)
    worker.start()
    worker.join()
    assert built == [worker.ident]


def test_resume_handler_only_signals_agent():
    class FakeAgent:
        calls = 0

        def resume(self):
            type(self).calls += 1

    app = tui.JeviumApp(lambda: FakeAgent(), goals=["g"], max_steps=60)
    app.agent = FakeAgent()
    app.handle_resume()
    app.handle_resume()
    assert FakeAgent.calls == 2


def test_request_stop_sets_flag_and_resumes():
    class FakeAgent:
        resumed = 0
        def resume(self):
            type(self).resumed += 1

    app = tui.JeviumApp(lambda: FakeAgent(), goals=["g"], max_steps=60)
    app.agent = FakeAgent()
    assert app._stopped is False
    app._request_stop()
    assert app._stopped is True
    assert FakeAgent.resumed == 1

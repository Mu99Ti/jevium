"""TUI helpers and resume wiring. No event loop, no browser."""

import asyncio
import threading

from textual.widgets import Button, RichLog, Static

from jevium import tui


def _collect_ids(widget):
    ids = set()
    if widget.id:
        ids.add(widget.id)
    for child in widget.children:
        ids.update(_collect_ids(child))
    return ids


def _assert_on_screen(app, selector):
    assert app.screen.size == (80, 24)
    region = app.query_one(selector).region
    assert region.width > 0
    assert region.height > 0
    assert region.x >= 0
    assert region.y >= 0
    assert region.x + region.width <= app.screen.size.width
    assert region.y + region.height <= app.screen.size.height


def test_compose_shows_dashboard_state_only():
    app = tui.JeviumApp(lambda: None, goals=["g"], max_steps=60)
    app.run_worker = lambda *args, **kwargs: None

    async def collect_ids():
        async with app.run_test(size=(80, 24)):
            ids = set()
            for widget in app.screen.children:
                ids.update(_collect_ids(widget))
            steps = str(app.query_one("#steps", Static).render())
            return ids, steps

    ids, steps = asyncio.run(collect_ids())
    assert {
        "meta",
        "status",
        "goal",
        "steps",
        "elapsed",
        "banner",
        "resume",
        "active",
        "log",
    } <= ids
    assert "progress" not in ids
    assert "elements" not in ids
    assert "decision" not in ids
    assert steps == "0 actions"


def test_render_updates_dashboard_and_focuses_resume():
    app = tui.JeviumApp(lambda: None, goals=["Find the docs"], max_steps=60)
    app.run_worker = lambda *args, **kwargs: None
    state = {
        "status": "waiting_human",
        "decision": None,
        "waiting": {"reason": "Payment confirmation"},
        "elements": [],
        "page": {"url": "https://example.test", "title": "Example", "actions": []},
        "history": [{"step": 1, "kind": "click", "action": "Open docs"}],
        "elapsed_ms": 1250,
        "plan": ["Find the docs"],
    }

    async def render():
        async with app.run_test(size=(80, 24)) as pilot:
            app._render(state)
            await pilot.pause()
            status = app.query_one("#status", Static)
            goal = app.query_one("#goal", Static)
            steps = app.query_one("#steps", Static)
            elapsed = app.query_one("#elapsed", Static)
            banner = app.query_one("#banner")
            resume = app.query_one("#resume", Button)
            log = app.query_one("#log", RichLog)
            assert str(status.render()) == "HUMAN ACTION"
            assert str(goal.render()) == "Find the docs"
            assert str(steps.render()) == "1 action"
            assert str(elapsed.render()) == "1.2 s"
            assert "status-waiting" in status.classes
            assert banner.has_class("visible")
            assert resume.display
            assert app.focused is resume
            _assert_on_screen(app, "#banner")
            _assert_on_screen(app, "#banner-message")
            _assert_on_screen(app, "#resume")
            _assert_on_screen(app, "#log")
            assert app.query_one("#banner-message", Static).region.height >= 2
            assert log.region.height >= 3
            assert any("Open docs" in str(line) for line in log.lines)
            assert not app.screen.show_vertical_scrollbar

    asyncio.run(render())


def test_render_hides_hitl_controls_when_running():
    app = tui.JeviumApp(lambda: None, goals=["g"], max_steps=60)
    app.run_worker = lambda *args, **kwargs: None
    state = {
        "status": "predicted",
        "decision": None,
        "waiting": None,
        "elements": [],
        "page": {"url": "https://example.test", "title": "Example", "actions": []},
        "history": [],
        "elapsed_ms": 0,
        "plan": ["g"],
    }

    async def render():
        async with app.run_test(size=(80, 24)):
            app._render(state)
            banner = app.query_one("#banner")
            resume = app.query_one("#resume", Button)
            assert not banner.has_class("visible")
            assert not resume.display
            assert not app.screen.show_vertical_scrollbar

    asyncio.run(render())


def test_resume_button_hides_banner_and_signals_agent():
    class FakeAgent:
        calls = 0

        def resume(self):
            type(self).calls += 1

    app = tui.JeviumApp(lambda: FakeAgent(), goals=["g"], max_steps=60)
    app.agent = FakeAgent()
    app.run_worker = lambda *args, **kwargs: None
    state = {
        "status": "waiting_human",
        "decision": None,
        "waiting": {"reason": "Payment confirmation"},
        "elements": [],
        "page": {"url": "https://example.test", "title": "Example", "actions": []},
        "history": [],
        "elapsed_ms": 0,
        "plan": ["g"],
    }

    async def click_resume():
        async with app.run_test(size=(80, 24)) as pilot:
            app._render(state)
            await pilot.pause()
            await pilot.click("#resume")
            assert FakeAgent.calls == 1
            assert not app.query_one("#banner").has_class("visible")
            assert not app.query_one("#resume").display

    asyncio.run(click_resume())


def test_active_line_reports_running_step():
    state = {
        "status": "predicted",
        "decision": {"operation": "CLICK", "target": "7", "choice": "e7"},
        "elements": [{"index": "7", "label": "Open article"}],
        "page": {"actions": []},
        "history": [],
    }
    assert tui._active_line(state) == "Next step: CLICK — Open article [7]"


def test_active_line_reports_waiting_human():
    state = {
        "status": "waiting_human",
        "decision": None,
        "waiting": {"reason": "Payment confirmation"},
        "elements": [],
        "page": {"actions": []},
        "history": [],
    }
    assert tui._active_line(state) == "Human action: Payment confirmation"


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

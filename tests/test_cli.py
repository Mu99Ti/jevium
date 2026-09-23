"""CLI contracts: startup validation, exit codes, summary. No browsers, no APIs."""

import threading

from jevium import cli, planner, verifier


def fresh_env(monkeypatch):
    monkeypatch.setattr(cli, "load_env", lambda: None)
    monkeypatch.setattr(planner, "plan", lambda task: [task])
    monkeypatch.setattr(verifier, "verify",
                        lambda *a: {"success": True, "reason": "ok"})


def test_missing_typesafe_key_exits_2(monkeypatch):
    fresh_env(monkeypatch)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert cli.main(["run", "--url", "https://x.test", "--task", "t", "--plain"]) == 2


def test_invalid_profile_exits_2(monkeypatch):
    fresh_env(monkeypatch)
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    assert cli.main(["run", "--url", "https://x.test", "--task", "t",
                     "--profile", "../evil", "--plain"]) == 2


def test_harness_backend_rejects_chromium_flags(monkeypatch):
    fresh_env(monkeypatch)
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    assert cli.main(["run", "--url", "https://x.test", "--task", "t",
                     "--backend", "harness", "--headless", "--plain"]) == 2


class FakeAgent:
    def __init__(self, url, goals, *, browser_factory=None, max_steps=None, **_kw):
        self.closed = False

    def run(self, on_waiting=None):
        yield {
            "status": "done", "elapsed_ms": 1200, "history": [{"action": "Click Go"}],
            "page": {"url": "https://x.test/done", "title": "Done", "text": "done"},
            "waiting": None, "plan": ["t"],
        }

    def resume(self):
        pass

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        self.close()


def test_plain_done_exits_zero(monkeypatch, capsys):
    fresh_env(monkeypatch)
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    monkeypatch.setattr(cli, "Agent", FakeAgent)
    code = cli.main(["run", "--url", "https://x.test", "--task", "t", "--plain"])
    out = capsys.readouterr().out
    assert code == 0
    assert "verdict" in out and "https://x.test/done" in out


def test_plain_blocked_exits_one(monkeypatch):
    fresh_env(monkeypatch)
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")

    class Blocked(FakeAgent):
        def run(self, on_waiting=None):
            yield {
                "status": "blocked", "elapsed_ms": 900, "history": [],
                "page": {"url": "https://x.test/", "title": "t", "text": ""},
                "waiting": None, "plan": ["t"],
            }

    monkeypatch.setattr(cli, "Agent", Blocked)
    assert cli.main(["run", "--url", "https://x.test", "--task", "t", "--plain"]) == 1


def test_plain_prompts_and_resumes_on_waiting(monkeypatch):
    fresh_env(monkeypatch)
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    resumed = []

    class Waiting(FakeAgent):
        def run(self, on_waiting=None):
            yield {
                "status": "waiting_human", "elapsed_ms": 10, "history": [],
                "page": {"url": "u", "title": "t", "text": ""},
                "waiting": {"trigger": "pay", "reason": "pay reason"}, "plan": ["t"],
            }
            on_waiting({"trigger": "pay", "reason": "pay reason"})
            resumed.append("resume()")
            yield {
                "status": "done", "elapsed_ms": 20, "history": [],
                "page": {"url": "u", "title": "t", "text": ""},
                "waiting": None, "plan": ["t"],
            }

    monkeypatch.setattr(cli, "Agent", Waiting)
    monkeypatch.setattr(cli, "_prompt_resume", lambda reason: None)
    assert cli.main(["run", "--url", "https://x.test", "--task", "t", "--plain"]) == 0
    assert resumed == ["resume()"]


def test_summary_lists_fields():
    state = {
        "status": "done", "elapsed_ms": 1500, "history": [1, 2, 3],
        "page": {"url": "https://final.test/"},
        "waiting": None, "plan": ["a", "b"],
    }
    verdict = {"success": True, "reason": "met"}
    text = "\n".join(cli.summary_lines(state, verdict, max_steps=60))
    for needle in ("done", "https://final.test/", "3/60", "met", "a"):
        assert needle in text


def test_blocked_run_skips_paid_verifier(monkeypatch):
    fresh_env(monkeypatch)
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    calls = []
    monkeypatch.setattr(verifier, "verify",
                        lambda *a: calls.append(1) or {"success": None, "reason": "x"})

    class Blocked(FakeAgent):
        def run(self, on_waiting=None):
            yield {
                "status": "blocked", "elapsed_ms": 900, "history": [],
                "page": {"url": "https://x.test/", "title": "t", "text": ""},
                "waiting": None, "plan": ["t"],
            }

    monkeypatch.setattr(cli, "Agent", Blocked)
    assert cli.main(["run", "--url", "https://x.test", "--task", "t", "--plain"]) == 1
    assert calls == []


def test_empty_task_exits_2(monkeypatch):
    fresh_env(monkeypatch)
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    assert cli.main(["run", "--url", "https://x.test", "--task", "   ", "--plain"]) == 2


def test_tui_defers_agent_creation_until_tui_worker(monkeypatch):
    from jevium import tui

    fresh_env(monkeypatch)
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    created = []

    class FakeAgent:
        def __init__(self, *args, **kwargs):
            created.append(threading.get_ident())

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

    monkeypatch.setattr(cli, "Agent", FakeAgent)
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli.sys.stdout, "isatty", lambda: True)

    def fake_run_tui(agent_factory, *, goals, max_steps=None):
        assert callable(agent_factory)
        assert created == []
        return 0

    monkeypatch.setattr(tui, "run_tui", fake_run_tui)
    assert cli.main(["run", "--url", "https://x.test", "--task", "t"]) == 0
    assert created == []

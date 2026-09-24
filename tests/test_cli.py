"""CLI contracts: startup validation, exit codes, summary. No browsers, no APIs."""

import threading
from unittest.mock import Mock

from jevium import cli, planner, verifier


def fresh_env(monkeypatch):
    monkeypatch.setattr(cli, "load_env", lambda: None)
    monkeypatch.setattr(planner, "plan", lambda task=None, **kwargs: [task])
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
    assert " 1 action  done" in out
    assert " 1 actions  done" not in out
    assert "actions   : 1\n" in out


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
    for needle in ("done", "https://final.test/", "actions   : 3", "met", "a"):
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


def test_plain_eof_does_not_resume(monkeypatch, capsys):
    fresh_env(monkeypatch)
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")

    class Waiting(FakeAgent):
        resumed = False

        def run(self, on_waiting=None):
            yield {
                "status": "waiting_human", "elapsed_ms": 10, "history": [],
                "page": {"url": "u", "title": "t", "text": ""},
                "waiting": {"trigger": "pay", "reason": "pay reason",
                            "element": {"label": "Pay now"}},
                "plan": ["t"],
            }
            on_waiting({"trigger": "pay", "reason": "pay reason"})
            return  # old code resumes on EOF and ends here; new code raises inside on_waiting

        def resume(self):
            type(self).resumed = True

    def eof(_prompt=""):
        raise EOFError

    monkeypatch.setattr(cli, "Agent", Waiting)
    monkeypatch.setattr("builtins.input", eof)
    assert cli.main(["run", "--url", "https://x.test", "--task", "t", "--plain"]) == 1
    assert Waiting.resumed is False
    assert "stdin closed while waiting for human" in capsys.readouterr().err


def test_task_with_configured_password_exits_2(monkeypatch, capsys):
    fresh_env(monkeypatch)
    monkeypatch.setattr(planner, "plan", Mock(side_effect=AssertionError("planner must not run")))
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    monkeypatch.setenv("JEVIUM_PASSWORD", "not-a-real-secret")
    code = cli.main(["run", "--url", "https://x.test",
                     "--task", "sign in with not-a-real-secret", "--plain"])
    assert code == 2
    assert "remove secrets from --task" in capsys.readouterr().err


def test_prompt_resume_copy(monkeypatch, capsys):
    prompts = []

    def fake_input(prompt):
        prompts.append(prompt)
        return ""

    monkeypatch.setattr("builtins.input", fake_input)
    cli._prompt_resume("Payment confirmation. Element: Go.")
    err = capsys.readouterr().err
    assert "Payment confirmation. Element: Go." in err
    assert prompts == ["Complete this step in the browser, "
                       "then press Enter to mark it done and continue... "]


def _replay_cli_setup(monkeypatch, tmp_path, body='{"step":1,"kind":"click","choice":"e3"}\n'):
    import jevium_core.chromium as chromium_mod
    import jevium_core.replay as replay_mod

    fresh_env(monkeypatch)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr(planner, "plan", Mock(side_effect=AssertionError("planner must not run")))
    browser = Mock()
    browser_factory = Mock(return_value=browser)
    monkeypatch.setattr(chromium_mod, "Browser", browser_factory)
    steps = tmp_path / "steps.jsonl"
    steps.write_text(body)
    return replay_mod, browser_factory, browser, steps


def test_replay_runs_without_model_key(monkeypatch, tmp_path):
    replay_mod, _factory, browser, steps = _replay_cli_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(replay_mod, "replay", Mock(return_value={
        "status": "done",
        "history": [{"step": 1, "kind": "click", "action": "Go",
                     "url": "https://x.test/done"}],
        "final_page": {"url": "https://x.test/done", "title": "D", "text": ""},
    }))
    code = cli.main(["run", "--url", "https://x.test", "--task", "t",
                     "--replay", str(steps), "--plain"])
    assert code == 0
    replay_mod.replay.assert_called_once()
    browser.close.assert_called_once()


def test_replay_with_record_exits_2(monkeypatch, tmp_path):
    _replay, browser_factory, _browser, steps = _replay_cli_setup(monkeypatch, tmp_path)
    code = cli.main(["run", "--url", "https://x.test", "--task", "t",
                     "--replay", str(steps), "--record", "--plain"])
    assert code == 2
    browser_factory.assert_not_called()


def test_replay_drift_exits_1(monkeypatch, tmp_path, capsys):
    replay_mod, _factory, _browser, steps = _replay_cli_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(replay_mod, "replay", Mock(
        side_effect=replay_mod.ReplayDrift(3, "button 'Go' not found", "https://x.test/step")))
    code = cli.main(["run", "--url", "https://x.test", "--task", "t",
                     "--replay", str(steps), "--plain"])
    assert code == 1
    err = capsys.readouterr().err
    assert "replay drifted at step 3" in err
    assert "button 'Go' not found" in err
    assert "https://x.test/step" in err


def test_replay_missing_file_exits_2_before_browser(monkeypatch, tmp_path):
    _replay, browser_factory, _browser, _steps = _replay_cli_setup(monkeypatch, tmp_path)
    code = cli.main(["run", "--url", "https://x.test", "--task", "t",
                     "--replay", str(tmp_path / "nope.jsonl"), "--plain"])
    assert code == 2
    browser_factory.assert_not_called()


def test_plain_provider_runtime_error_exits_one(monkeypatch, capsys):
    fresh_env(monkeypatch)
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")

    class RateLimited(FakeAgent):
        def run(self, on_waiting=None):
            raise RuntimeError("Model provider returned HTTP 429; no action executed.")
            yield

    monkeypatch.setattr(cli, "Agent", RateLimited)
    assert cli.main(["run", "--url", "https://x.test", "--task", "t", "--plain"]) == 1
    assert "Model provider returned HTTP 429" in capsys.readouterr().err

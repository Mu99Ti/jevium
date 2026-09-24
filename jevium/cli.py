"""jevium run — give it a site and a task."""

import argparse
import json
import os
import re
import sys
import time
from functools import partial
from pathlib import Path

from jevium_core import Agent, replay
from jevium_core.export_test import render_playwright_test
from jevium_core.model import task_contains_configured_secret

from . import planner, verifier
from .report import render_report, report_format


def load_env():
    path = Path.cwd() / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key, value)


def _profile_path(name: str | None) -> str | None | bool:
    if name is None:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
        print(f"jevium: invalid --profile name: {name!r}", file=sys.stderr)
        return False  # sentinel: invalid
    return name


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="jevium", description="Run a site+task browser agent.")
    sub = p.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Execute a task on a page.")
    run.add_argument("--url", required=True)
    run.add_argument("--task", required=True)
    run.add_argument("--headless", action="store_true")
    run.add_argument("--profile", default=None)
    run.add_argument("--record", action="store_true")
    run.add_argument("--plain", action="store_true", help="Line logs instead of the TUI.")
    run.add_argument("--backend", choices=("chromium", "harness"), default="chromium")
    run.add_argument("--max-steps", type=int, default=None)
    run.add_argument("--replay", metavar="STEPS", default=None,
                     help="Replay a recorded steps.jsonl without model calls.")
    run.add_argument("--export-test", metavar="PATH", default=None,
                     help="Write a Playwright Test spec after a completed run.")
    run.add_argument("--report", metavar="PATH", default=None,
                     help="Write a JSON or JUnit XML run report (CI).")
    run.add_argument("--wait-idle", action="store_true",
                     help="Wait for network idle after each observation (chromium only).")
    return p.parse_args(argv)


def _action_count_text(count):
    return f"{count} action" if count == 1 else f"{count} actions"


def summary_lines(state, verdict, max_steps=None):
    page = state.get("page") or {}
    goals = state.get("plan") or []
    actions = len(state.get("history") or [])
    return [
        f"status    : {state.get('status')}",
        f"final url : {page.get('url', '')}",
        f"elapsed   : {state.get('elapsed_ms', 0)} ms",
        f"actions   : {actions}",
        "goals     : " + ("; ".join(goals) if goals else "-"),
        f"verdict   : {verdict.get('success')} — {verdict.get('reason')}",
    ]


def _prompt_resume(reason: str):
    print(f"\n[waiting for human] {reason}", file=sys.stderr)
    try:
        input("Complete this step in the browser, then press Enter to mark it done and continue... ")
    except EOFError:
        raise RuntimeError("stdin closed while waiting for human; resume was not sent.") from None


def run_plain(agent, goals, *, max_steps=None, export_path=None, report_path=None, start_url=None):
    def on_waiting(waiting):
        _prompt_resume(waiting.get("reason", "Human intervention required."))
        agent.resume()
        print("[human step marked done] rechecking page and continuing...", file=sys.stderr)

    final = None
    try:
        for state in agent.run(on_waiting=on_waiting):
            final = state
            actions = len(state.get("history") or [])
            print(f"{state.get('elapsed_ms', 0):>5} ms  "
                  f"{_action_count_text(actions)}  {state.get('status')}")
    except (ValueError, RuntimeError) as exc:
        agent.final_state = final
        print(f"jevium: {exc}", file=sys.stderr)
        return 1
    agent.final_state = final
    if final is None:
        print("jevium: run produced no state", file=sys.stderr)
        return 1
    if final.get("status") == "done":
        verdict = verifier.verify(goals, final.get("page") or {}, final.get("history") or [])
    else:
        verdict = {"success": None, "reason": f"run ended {final.get('status')}; not verified."}
    agent.final_verdict = verdict
    print()
    for line in summary_lines(final, verdict):
        print(line)
    if export_path:
        if final.get("status") == "done":
            try:
                path = Path(export_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(render_playwright_test(
                    task="; ".join(str(g) for g in goals),
                    start_url=start_url or "",
                    history=final.get("history") or [],
                    final_page=final.get("page") or {},
                ))
            except OSError as exc:
                print(f"jevium: export failed: {exc}", file=sys.stderr)
        else:
            print("jevium: export skipped: run did not complete", file=sys.stderr)
    if report_path:
        fmt = report_format(report_path)
        try:
            path = Path(report_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(render_report(final, verdict, fmt))
        except OSError as exc:
            print(f"jevium: report failed: {exc}", file=sys.stderr)
    return 0 if final.get("status") == "done" else 1


def _start_browser(args, profile):
    if args.backend == "chromium":
        try:
            from jevium_core import chromium
        except ImportError as exc:
            raise RuntimeError(f"playwright is not installed ({exc}); run: uv sync") from None
        return chromium.Browser(args.url, headless=args.headless, profile=profile,
                                wait_idle=args.wait_idle)
    from jevium_core.browser import Browser
    return Browser(args.url)


def _save_failure_artifacts(agent):
    if agent is None or not hasattr(agent, "save_failure_artifacts"):
        return None
    directory = getattr(agent, "record_dir", None) or (
        Path("runs") / f"failure-{time.strftime('%Y%m%d-%H%M%S')}")
    results_json = None
    state = getattr(agent, "final_state", None)
    verdict = getattr(agent, "final_verdict", None) or {
        "success": None, "reason": "run failed before verification", "checks": []}
    if state is not None:
        results_json = render_report(state, verdict, "json")
    try:
        agent.save_failure_artifacts(directory, results_json=results_json)
    except Exception as exc:
        print(f"jevium: failed to save artifacts: {exc}", file=sys.stderr)
        return None
    print(f"jevium: failure artifacts saved to {directory}", file=sys.stderr)
    return directory


def main(argv=None) -> int:
    try:
        load_env()
        args = parse_args(argv)
    except SystemExit as exc:
        # argparse: --help exits 0 (must stay 0), errors exit 2.
        return int(exc.code) if exc.code is not None else 2

    if not args.replay and not os.environ.get("TYPESAFE_API_KEY"):
        print("jevium: TYPESAFE_API_KEY is required.", file=sys.stderr)
        return 2
    if not args.task.strip():
        print("jevium: --task must not be empty.", file=sys.stderr)
        return 2
    if task_contains_configured_secret(args.task):
        print("jevium: remove secrets from --task; put them in .env.", file=sys.stderr)
        return 2
    if args.report and report_format(args.report) is None:
        print("jevium: --report must end in .json or .xml", file=sys.stderr)
        return 2
    if not args.replay and not os.environ.get("TEXT_MODEL_API_KEY"):
        print("jevium: warning: no TEXT_MODEL_API_KEY — TYPE_TEXT will abort at the first fill; "
              "planner/verifier skipped.", file=sys.stderr)

    profile = _profile_path(args.profile)
    if profile is False:
        return 2
    if args.backend == "harness" and (args.headless or args.profile or args.wait_idle):
        print("jevium: --headless/--profile/--wait-idle require --backend chromium.", file=sys.stderr)
        return 2

    browser_factory = None
    if args.backend == "chromium":
        try:
            from jevium_core import chromium
        except ImportError as exc:
            print(f"jevium: playwright is not installed ({exc}); run: uv sync", file=sys.stderr)
            return 2
        browser_factory = partial(chromium.Browser, headless=args.headless,
                                  profile=profile, wait_idle=args.wait_idle)

    record_dir = None
    if args.record:
        record_dir = Path("runs") / time.strftime("%Y%m%d-%H%M%S")

    if args.replay:
        if args.record:
            print("jevium: --record cannot be combined with --replay.", file=sys.stderr)
            return 2
        try:
            steps = replay.load_steps(args.replay)
        except (OSError, ValueError) as exc:
            print(f"jevium: {exc}", file=sys.stderr)
            return 2
        try:
            browser = _start_browser(args, profile)
        except RuntimeError as exc:
            print(f"jevium: {exc}", file=sys.stderr)
            return 2
        try:
            result = replay.replay(browser, steps)
        except replay.ReplayDrift as exc:
            print(f"jevium: replay drifted at step {exc.index}: {exc.reason} (at {exc.url})",
                  file=sys.stderr)
            directory = Path("runs") / f"failure-{time.strftime('%Y%m%d-%H%M%S')}"
            try:
                directory.mkdir(parents=True, exist_ok=True)
                browser.save_failure_artifacts(directory)
                (directory / "drift.json").write_text(
                    json.dumps({"step": exc.index, "reason": exc.reason, "url": exc.url},
                               indent=2) + "\n")
                print(f"jevium: failure artifacts saved to {directory}", file=sys.stderr)
            except Exception as save_exc:
                print(f"jevium: failed to save replay artifacts: {save_exc}", file=sys.stderr)
            return 1
        finally:
            browser.close()
        state = {"status": "done", "page": result["final_page"], "elapsed_ms": 0,
                 "history": result["history"], "plan": [args.task]}
        verdict = verifier.verify(
            [args.task], result["final_page"], result["history"],
            expected_url=steps[-1].get("url"),
        )
        if args.report:
            try:
                path = Path(args.report)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(render_report(state, verdict, report_format(args.report)))
            except OSError as exc:
                print(f"jevium: report failed: {exc}", file=sys.stderr)
        if args.export_test:
            try:
                path = Path(args.export_test)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(render_playwright_test(
                    task=args.task, start_url=args.url,
                    history=result["history"], final_page=result["final_page"],
                ))
            except OSError as exc:
                print(f"jevium: export failed: {exc}", file=sys.stderr)
        print()
        for line in summary_lines(state, verdict):
            print(line)
        return 0 if verdict.get("success") is not False else 1

    goals = planner.plan(args.task, url=args.url)

    def create_agent():
        try:
            return Agent(
                args.url, goals,
                browser_factory=browser_factory,
                max_steps=args.max_steps,
                record_dir=record_dir,
            )
        except Exception as exc:
            message = str(exc)
            if "playwright install" in message or "Executable doesn't exist" in message:
                message += " — run: uv run playwright install chromium"
            raise RuntimeError(f"failed to start browser: {message}") from None

    if not args.plain and sys.stdin.isatty() and sys.stdout.isatty():
        from .tui import run_tui
        return run_tui(create_agent, goals=goals, max_steps=args.max_steps,
                       export_path=args.export_test, report_path=args.report,
                       start_url=args.url)

    try:
        agent = create_agent()
    except Exception as exc:
        print(f"jevium: {exc}", file=sys.stderr)
        return 1

    try:
        with agent:
            code = run_plain(agent, goals, max_steps=args.max_steps,
                             export_path=args.export_test, report_path=args.report,
                             start_url=args.url)
            if code != 0:
                _save_failure_artifacts(agent)
            return code
    except KeyboardInterrupt:
        print("\njevium: interrupted.", file=sys.stderr)
        _save_failure_artifacts(agent)
        return 130
    except ValueError as exc:
        print(f"jevium: {exc}", file=sys.stderr)
        _save_failure_artifacts(agent)
        return 1

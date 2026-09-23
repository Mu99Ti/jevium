"""jevium run — give it a site and a task."""

import argparse
import os
import re
import sys
import time
from functools import partial
from pathlib import Path

from jevium_core import Agent

from . import planner, verifier


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
    return p.parse_args(argv)


def summary_lines(state, verdict, max_steps=60):
    page = state.get("page") or {}
    goals = state.get("plan") or []
    return [
        f"status    : {state.get('status')}",
        f"final url : {page.get('url', '')}",
        f"elapsed   : {state.get('elapsed_ms', 0)} ms",
        f"steps     : {len(state.get('history') or [])}/{max_steps}",
        "goals     : " + ("; ".join(goals) if goals else "-"),
        f"verdict   : {verdict.get('success')} — {verdict.get('reason')}",
    ]


def _prompt_resume(reason: str):
    print(f"\n[waiting for human] {reason}", file=sys.stderr)
    try:
        input("Complete the step in the browser, then press Enter to resume... ")
    except EOFError:
        pass


def run_plain(agent, goals, *, max_steps=None):
    def on_waiting(waiting):
        _prompt_resume(waiting.get("reason", "Human intervention required."))
        agent.resume()

    final = None
    try:
        for state in agent.run(on_waiting=on_waiting):
            final = state
            print(f"{state.get('elapsed_ms', 0):>5} ms  {len(state.get('history') or [])} actions  "
                  f"{state.get('status')}")
    except ValueError as exc:
        print(f"jevium: {exc}", file=sys.stderr)
        return 1
    if final is None:
        print("jevium: run produced no state", file=sys.stderr)
        return 1
    if final.get("status") == "done":
        verdict = verifier.verify(goals, final.get("page") or {}, final.get("history") or [])
    else:
        verdict = {"success": None, "reason": f"run ended {final.get('status')}; not verified."}
    print()
    for line in summary_lines(final, verdict, max_steps=max_steps or 60):
        print(line)
    return 0 if final.get("status") == "done" else 1


def main(argv=None) -> int:
    try:
        load_env()
        args = parse_args(argv)
    except SystemExit as exc:
        # argparse: --help exits 0 (must stay 0), errors exit 2.
        return int(exc.code) if exc.code is not None else 2

    if not os.environ.get("TYPESAFE_API_KEY"):
        print("jevium: TYPESAFE_API_KEY is required.", file=sys.stderr)
        return 2
    if not args.task.strip():
        print("jevium: --task must not be empty.", file=sys.stderr)
        return 2
    if not os.environ.get("TEXT_MODEL_API_KEY"):
        print("jevium: warning: no TEXT_MODEL_API_KEY — TYPE_TEXT will abort at the first fill; "
              "planner/verifier skipped.", file=sys.stderr)

    profile = _profile_path(args.profile)
    if profile is False:
        return 2
    if args.backend == "harness" and (args.headless or args.profile):
        print("jevium: --headless/--profile require --backend chromium.", file=sys.stderr)
        return 2

    browser_factory = None
    if args.backend == "chromium":
        try:
            from jevium_core import chromium
        except ImportError as exc:
            print(f"jevium: playwright is not installed ({exc}); run: uv sync", file=sys.stderr)
            return 2
        browser_factory = partial(chromium.Browser, headless=args.headless, profile=profile)

    record_dir = None
    if args.record:
        record_dir = Path("runs") / time.strftime("%Y%m%d-%H%M%S")

    goals = planner.plan(args.task)

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
        return run_tui(create_agent, goals=goals, max_steps=args.max_steps)

    try:
        agent = create_agent()
    except Exception as exc:
        print(f"jevium: {exc}", file=sys.stderr)
        return 1

    try:
        with agent:
            return run_plain(agent, goals, max_steps=args.max_steps)
    except KeyboardInterrupt:
        print("\njevium: interrupted.", file=sys.stderr)
        return 130
    except ValueError as exc:
        print(f"jevium: {exc}", file=sys.stderr)
        return 1

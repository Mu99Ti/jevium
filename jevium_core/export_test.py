"""Render a recorded run as a deterministic Playwright Test. Code-owned locators only."""

import json

from .model import SENSITIVE_ENV


def _locator_expr(loc):
    if loc.get("testid"):
        expr = f"page.getByTestId({json.dumps(loc['testid'])})"
    elif loc.get("role") is not None and loc.get("name") is not None:
        expr = (f"page.getByRole({json.dumps(loc['role'])}, "
                f"{{ name: {json.dumps(loc['name'])} }})")
    else:
        return None
    nth = int(loc.get("nth", 0) or 0)
    if nth:
        expr += f".nth({nth})"
    return expr


def render_playwright_test(*, task, start_url, history, final_page) -> str:
    lines = [
        "import { test, expect } from '@playwright/test';",
        "",
        f"test({json.dumps(task)}, async ({{ page }}) => {{",
        f"  await page.goto({json.dumps(start_url)});",
    ]
    for step in history:
        loc = step.get("locator") or {}
        kind = step.get("kind")
        if kind == "wait":
            lines.append(f"  await page.waitForTimeout({int(loc.get('ms', 100))});")
            continue
        if kind == "scroll":
            lines.append(f"  await page.mouse.wheel({{ deltaY: {int(loc.get('delta', 560))} }});")
            continue
        expr = _locator_expr(loc)
        if expr is None:
            lines.append(f"  // skipped step {step.get('step')}: no recorded locator")
            continue
        if kind == "fill":
            if loc.get("secret"):
                lines.append(f"  await {expr}.fill(process.env.{SENSITIVE_ENV[loc['secret']]}!);")
            else:
                lines.append(f"  await {expr}.fill({json.dumps(step.get('text') or '')});")
        elif kind == "select":
            option = loc.get("option_value")
            lines.append(f"  await {expr}.selectOption({json.dumps(option if option is not None else '')});")
        else:
            lines.append(f"  await {expr}.click();")
    lines += [
        f"  await expect(page).toHaveURL({json.dumps(final_page.get('url', ''))});",
        f"  await expect(page).toHaveTitle({json.dumps(final_page.get('title', ''))});",
        "});",
        "",
    ]
    return "\n".join(lines)

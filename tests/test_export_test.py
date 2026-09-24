"""Playwright Test export rendering. Pure string contracts; no browser, no model."""

import json

from jevium_core import export_test


def render(history, task="Find boots", start_url="https://x.test/"):
    return export_test.render_playwright_test(
        task=task, start_url=start_url, history=history,
        final_page={"url": "https://x.test/done", "title": "Done"},
    )


def test_goto_role_click_and_final_assertions():
    out = render([{"step": 1, "kind": "click", "text": None, "locator": {
        "kind": "click", "role": "button", "name": "Go", "nth": 0}}])
    assert "import { test, expect } from" in out
    assert 'test("Find boots", async ({ page }) => {' in out
    assert 'await page.goto("https://x.test/");' in out
    assert 'page.getByRole("button", { name: "Go" })' in out
    assert ".click();" in out
    assert ".nth(" not in out
    assert 'await expect(page).toHaveURL("https://x.test/done");' in out
    assert 'await expect(page).toHaveTitle("Done");' in out


def test_fill_uses_json_string_escaping_and_nth():
    text = 'say "hi"\nnext'
    out = render([{"step": 1, "kind": "fill", "text": text, "locator": {
        "kind": "fill", "role": "textbox", "name": "Search", "nth": 2}}])
    assert ".nth(2)" in out
    assert (".fill(" + json.dumps(text) + ");") in out


def test_secret_fill_uses_env_never_literal():
    out = render([{"step": 1, "kind": "fill", "text": "***", "locator": {
        "kind": "fill", "role": "textbox", "name": "Password", "nth": 0,
        "secret": "password"}}])
    assert "process.env.JEVIUM_PASSWORD!" in out
    assert '"***"' not in out


def test_testid_preferred_over_role():
    out = render([{"step": 1, "kind": "click", "text": None, "locator": {
        "kind": "click", "role": "button", "name": "Go", "nth": 0,
        "testid": "submit-btn"}}])
    assert 'page.getByTestId("submit-btn")' in out
    assert "getByRole" not in out


def test_select_wait_and_scroll():
    out = render([
        {"step": 1, "kind": "select", "text": None, "locator": {
            "kind": "select", "role": "combobox", "name": "Color", "nth": 0,
            "option_value": "red", "option_label": "Red"}},
        {"step": 2, "kind": "wait", "text": None, "locator": {"kind": "wait", "ms": 100}},
        {"step": 3, "kind": "scroll", "text": None, "locator": {"kind": "scroll", "delta": -560}},
    ])
    assert '.selectOption("red");' in out
    assert "await page.waitForTimeout(100);" in out
    assert "await page.mouse.wheel({ deltaY: -560 });" in out


def test_legacy_step_without_locator_is_commented():
    out = render([{"step": 9, "kind": "click", "text": None, "choice": "e9"}])
    assert "// skipped step 9: no recorded locator" in out

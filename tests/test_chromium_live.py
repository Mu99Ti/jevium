"""Live smoke: real Chromium, no model calls. Skips when the browser is unavailable."""

from pathlib import Path

import pytest

from jevium_core import chromium

pytestmark = pytest.mark.live
RISK_PAGE = (Path(__file__).parent / "pages" / "risk.html").resolve().as_uri()
LOGIN_PAGE = (Path(__file__).parent / "pages" / "login.html").resolve().as_uri()


def test_observe_and_act_roundtrip():
    try:
        browser = chromium.Browser(RISK_PAGE, headless=True)
    except Exception as exc:  # missing binary, sandbox issues
        pytest.skip(f"chromium unavailable: {exc}")
    try:
        state = browser.observe(screenshot=False)
        assert state["actions"]
        assert "captcha" in state.get("page_risks", [])
        pay = next(a for a in state["actions"] if a.get("risk") == "pay")
        otp = next(a for a in state["actions"] if a.get("risk") == "otp")
        assert otp["kind"] == "fill"
        assert browser.fresh(state) is True
        assert browser.evaluate("window.__clicked || 0") == 0
        browser.act(pay, state)
        assert browser.evaluate("window.__clicked || 0") == 1
    finally:
        browser.close()


def test_chromium_close_is_idempotent():
    b = chromium.Browser.__new__(chromium.Browser)
    b._pw = b._browser = b._context = b._cdp = None
    b.close()
    b.close()


def test_login_and_card_secrets_are_masked():
    try:
        browser = chromium.Browser(LOGIN_PAGE, headless=True)
    except Exception as exc:  # missing binary, sandbox issues
        pytest.skip(f"chromium unavailable: {exc}")
    try:
        state = browser.observe(screenshot=False)
        by_label = {a["label"]: a for a in state["actions"]}
        assert by_label["Username"]["secret"] == "username"
        assert by_label["Username"]["value"] == ""
        assert by_label["Username"].get("login_form") is True
        assert by_label["Username"]["testid"] == "user-field"
        assert by_label["Password"]["secret"] == "password"
        assert by_label["Password"]["risk"] == "credential"
        assert by_label["Password"]["value"] == ""
        assert by_label["Password"].get("login_form") is True
        assert by_label["Card number"]["secret"] == "card_number"
        assert by_label["Card number"]["risk"] == "card_number"
        assert by_label["CVC"]["secret"] == "card_cvv"
        assert by_label["CVC"]["risk"] == "card_cvv"
        assert by_label["Sign in"].get("login_form") is True
        assert by_label["Pay now"]["risk"] == "pay"
    finally:
        browser.close()


def test_actions_without_testid_omit_the_field():
    try:
        browser = chromium.Browser(RISK_PAGE, headless=True)
    except Exception as exc:
        pytest.skip(f"chromium unavailable: {exc}")
    try:
        state = browser.observe(screenshot=False)
        assert all("testid" not in a for a in state["actions"])
    finally:
        browser.close()


def test_reduced_motion_and_wait_idle():
    try:
        b = chromium.Browser(RISK_PAGE, headless=True, wait_idle=True)
    except TypeError:
        raise  # our missing parameter is a bug, not an environment skip
    except Exception as exc:
        pytest.skip(f"chromium unavailable: {exc}")
    try:
        assert b.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches") is True
        assert b.wait_idle is True
        b.settle()  # loaded fixture page: networkidle resolves or is swallowed
    finally:
        b.close()

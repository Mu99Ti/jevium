"""Live smoke: real Chromium, no model calls. Skips when the browser is unavailable."""

from pathlib import Path

import pytest

from jevium_core import chromium

pytestmark = pytest.mark.live
RISK_PAGE = (Path(__file__).parent / "pages" / "risk.html").resolve().as_uri()


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

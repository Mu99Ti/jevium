"""Self-managed Chromium through Playwright; same Browser contract as the harness backend."""

import re
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from .browser import BaseBrowser, StalePage  # noqa: F401  re-export for consumers


class Browser(BaseBrowser):
    def __init__(self, url, *, headless=False, profile=None, wait_idle=False):
        self.wait_idle = wait_idle
        self._pw = sync_playwright().start()
        self._browser = None
        self._context = None
        self._cdp = None
        try:
            viewport = {"width": 1120, "height": 780}
            if profile is not None:
                if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", profile):
                    raise ValueError("Invalid profile name")
                user_data = Path.home() / ".jevium" / "profiles" / profile
                user_data.mkdir(parents=True, exist_ok=True)
                self._context = self._pw.chromium.launch_persistent_context(
                    str(user_data), headless=headless, viewport=viewport,
                    reduced_motion="reduce",
                )
                self.page = self._context.pages[0] if self._context.pages else self._context.new_page()
            else:
                self._browser = self._pw.chromium.launch(headless=headless)
                self._context = self._browser.new_context(
                    viewport=viewport, reduced_motion="reduce")
                self.page = self._context.new_page()
            self._cdp = self._context.new_cdp_session(self.page)
            self.call("Emulation.setDeviceMetricsOverride", width=1120, height=780,
                      deviceScaleFactor=1, mobile=False)
            self.call("Emulation.setFocusEmulationEnabled", enabled=True)
            self.page.goto(url, wait_until="load", timeout=15000)
        except Exception:
            self.close()
            raise

    def call(self, method, **params):
        try:
            return self._cdp.send(method, params)
        except PlaywrightError as exc:
            raise StalePage(str(exc)) from None

    def settle(self):
        if not getattr(self, "wait_idle", False) or not getattr(self, "page", None):
            return
        try:
            self.page.wait_for_load_state("networkidle", timeout=1000)
        except Exception:
            pass

    def close(self):
        for closer in (
            lambda: self._cdp and self._cdp.detach(),
            lambda: self._context and self._context.close(),
            lambda: self._browser and self._browser.close(),
            lambda: self._pw and self._pw.stop(),
        ):
            try:
                closer()
            except Exception:
                pass
        self._cdp = self._context = self._browser = self._pw = None

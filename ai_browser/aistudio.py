"""
Google AI Studio browser client.

Automates https://aistudio.google.com/prompts/new_chat so that local servers
and personal apps can obtain AI responses without an API key.

Design philosophy
-----------------
* **Keyboard-first**: ``Ctrl+Enter`` (``Cmd+Enter`` on macOS) is used to
  submit prompts.  Button clicks are only attempted as a secondary fallback.
  Keyboard shortcuts are far more stable across UI changes.
* **Minimal selectors**: only a small, prioritised list of selectors is kept
  for each interaction point.  The most generic HTML attributes (``textarea``,
  ``[contenteditable]``) are tried last so that page-structure changes in
  AI Studio degrade gracefully rather than causing hard failures.
* **JS fallbacks**: when CSS selectors fail, JavaScript DOM queries are used
  to locate elements at runtime, providing an additional safety net.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any, Optional
from urllib.parse import urlparse

from .base import AIBrowserClient


# ---------------------------------------------------------------------------
# Selectors – ordered from most specific to most general.
# AI Studio is an Angular SPA whose component names change; keeping the list
# short and finishing with broad HTML selectors keeps things working longer.
# ---------------------------------------------------------------------------

# Prompt input area.
_INPUT_SELECTORS = [
    "ms-prompt-input rich-textarea .ql-editor",
    "ms-prompt-input [contenteditable='true']",
    "ms-prompt-input textarea",
    "rich-textarea .ql-editor",
    "[contenteditable='true']",
]

# Stop / loading indicator shown while the model is generating.
_STOP_SELECTORS = [
    "button[aria-label='Stop generation']",
    "button[aria-label='Stop']",
    ".stop-button",
]

# Last model-response container from which the reply text is extracted.
_RESPONSE_SELECTORS = [
    "ms-chat-turn[role='model']:last-of-type .chat-turn-content",
    "ms-chat-turn:last-of-type .model-response-text",
    ".model-response-text",
    "ms-text-chunk:last-of-type",
]

# JavaScript fallback: return the last non-empty text found in a model turn.
_RESPONSE_JS = """
() => {
    const candidates = [
        ...document.querySelectorAll('ms-chat-turn[role="model"] .chat-turn-content'),
        ...document.querySelectorAll('.model-response-text'),
        ...document.querySelectorAll('ms-text-chunk'),
    ];
    for (let i = candidates.length - 1; i >= 0; i--) {
        const t = (candidates[i].innerText || '').trim();
        if (t) return t;
    }
    return '';
}
"""

# Maximum time (ms) to wait for the response stream to finish.
_RESPONSE_TIMEOUT_MS = 180_000  # 3 minutes

# How long (ms) the response must be unchanged to be considered complete.
_STABILITY_DELAY_MS = 2_000

_MS = 1_000.0

# Platform-aware modifier key: Command on macOS, Control elsewhere.
_MOD = "Meta" if sys.platform == "darwin" else "Control"


class AIStudio(AIBrowserClient):
    """
    Browser-based client for `Google AI Studio
    <https://aistudio.google.com/prompts/new_chat>`_.

    The first time you run the client you must authenticate with your Google
    account.  Run once with ``headless=False`` so that the browser window is
    visible, log in through the normal Google sign-in flow, and then close the
    client.  On subsequent runs you can use ``headless=True``; your session is
    persisted in *profile_dir*.

    Example::

        # First run (visible browser – log in once)
        with AIStudio(headless=False) as ai:
            ai.chat("Say hello!")

        # Subsequent runs (headless)
        with AIStudio() as ai:
            print(ai.chat("What is the capital of France?"))
    """

    DEFAULT_URL = "https://aistudio.google.com/prompts/new_chat"

    def __init__(
        self,
        headless: bool = True,
        profile_dir: Optional[str] = None,
        timeout: int = 60_000,
        response_timeout: int = _RESPONSE_TIMEOUT_MS,
    ) -> None:
        """
        Parameters
        ----------
        headless:
            Run the browser without a visible window (default ``True``).
            Set to ``False`` on the first run to complete Google sign-in.
        profile_dir:
            Directory used to persist the browser profile between runs.
        timeout:
            Navigation / element-wait timeout in milliseconds (default 60 s).
        response_timeout:
            Maximum time in milliseconds to wait for the AI to finish
            generating a response (default 3 minutes).
        """
        super().__init__(headless=headless, profile_dir=profile_dir, timeout=timeout)
        self.response_timeout = response_timeout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chat(self, prompt: str) -> str:
        """Send *prompt* and return the AI's response as a string.

        Raises
        ------
        RuntimeError
            If the page is not ready or a response cannot be extracted.
        """
        if self._page is None:
            raise RuntimeError("Client is not started. Call start() or use as a context manager.")

        self._wait_for_page_ready()
        self._type_prompt(prompt)
        self._submit_prompt()
        return self._wait_for_response()

    def new_chat(self) -> None:
        """Navigate to a brand-new empty chat session."""
        if self._page is None:
            raise RuntimeError("Client is not started. Call start() or use as a context manager.")
        self._page.goto(self.DEFAULT_URL, timeout=self.timeout)
        self._wait_for_page_ready()

    def screenshot(self, path: str) -> None:
        """Save a screenshot of the current page to *path* (PNG).

        Useful for debugging when ``headless=True``.
        """
        if self._page is None:
            raise RuntimeError("Client is not started.")
        self._page.screenshot(path=path, full_page=False)

    # ------------------------------------------------------------------
    # Login check
    # ------------------------------------------------------------------

    def _ensure_logged_in(self) -> None:
        """Wait for Google sign-in if the browser was redirected to the login page."""
        page = self._page
        parsed = urlparse(page.url)
        netloc = parsed.netloc.lower()
        path = parsed.path.lower()

        on_signin_page = (
            netloc == "accounts.google.com"
            or netloc.endswith(".accounts.google.com")
            or "signin" in path
        )

        if not on_signin_page:
            return

        if self.headless:
            raise RuntimeError(
                "Not logged in to Google AI Studio.\n"
                "Run once with  headless=False  to open the browser, sign in\n"
                "with your Google account, and then close the client.\n"
                "Your session will be saved to:\n"
                f"  {self.profile_dir}\n"
                "After that you can use headless=True for all future runs."
            )

        print(
            "\n[ai_browser] Please log in to your Google account in the browser window.\n"
            "The script will continue automatically once sign-in is complete...\n"
        )
        # Wait up to 5 minutes for the user to complete sign-in.
        page.wait_for_url(
            "**/aistudio.google.com/**",
            timeout=300_000,
            wait_until="domcontentloaded",
        )
        # Persist the session so future runs can skip login.
        storage_state_path = os.path.join(self.profile_dir, "storage_state.json")
        self._context.storage_state(path=storage_state_path)
        print("[ai_browser] Sign-in complete – session saved. You can use headless=True from now on.\n")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _wait_for_page_ready(self) -> None:
        """Block until the prompt input is visible and interactive."""
        page = self._page
        # Confirm we are on an AI Studio page (not an error or redirect).
        page.wait_for_function(
            "document.title.includes('AI Studio') || document.title.includes('Google AI')",
            timeout=self.timeout,
        )
        # Wait for the input area to be present and visible.
        for selector in _INPUT_SELECTORS:
            try:
                page.wait_for_selector(selector, state="visible", timeout=10_000)
                return
            except Exception:
                continue
        raise RuntimeError(
            "AI Studio prompt input not found.\n"
            "Run with headless=False to inspect the page, or check for a UI update."
        )

    def _find_input(self) -> Any:
        """Return the first visible prompt-input element, or raise."""
        page = self._page
        for selector in _INPUT_SELECTORS:
            try:
                el = page.wait_for_selector(selector, state="visible", timeout=5_000)
                if el:
                    return el
            except Exception:
                continue
        raise RuntimeError("Could not locate the prompt input area in AI Studio.")

    def _type_prompt(self, prompt: str) -> None:
        """Focus the input area, clear it, and type *prompt*."""
        input_el = self._find_input()
        input_el.click()

        # Clear existing text: try JS first (works for contenteditable); fall
        # back to the select-all + Delete keyboard shortcut only if JS fails.
        try:
            input_el.evaluate("el => { el.textContent = ''; }")
        except Exception:
            input_el.press(f"{_MOD}+a")
            input_el.press("Delete")

        # fill() works for <textarea>; type() works for contenteditable.
        try:
            input_el.fill(prompt)
        except Exception:
            input_el.type(prompt)

    def _submit_prompt(self) -> None:
        """Submit the prompt.

        ``Ctrl+Enter`` (``Cmd+Enter`` on macOS) is the primary method because
        it is a stable keyboard shortcut that works regardless of button layout
        changes.  A Run-button click is attempted first only if the button is
        already visible, to avoid a slow timeout on every call.
        """
        page = self._page

        # Quick, non-blocking check for a visible Run button.
        for selector in [
            "run-button button:not([disabled])",
            "button[aria-label='Run']",
            "button[mattooltip='Run (Ctrl+Enter)']",
        ]:
            try:
                btn = page.query_selector(selector)
                if btn and btn.is_visible():
                    btn.click()
                    return
            except Exception:
                continue

        # Primary method: keyboard shortcut.
        page.keyboard.press(f"{_MOD}+Return")

    def _wait_for_response(self) -> str:
        """Wait for the model to finish generating and return the response."""
        page = self._page
        deadline = time.monotonic() + self.response_timeout / _MS

        # Phase 1 – wait for the stop indicator (generation started).
        generation_started = False
        for selector in _STOP_SELECTORS:
            try:
                page.wait_for_selector(selector, state="visible", timeout=15_000)
                generation_started = True
                break
            except Exception:
                continue

        # Phase 2 – wait for the stop indicator to disappear (generation done).
        if generation_started:
            for selector in _STOP_SELECTORS:
                try:
                    page.wait_for_selector(
                        selector, state="hidden", timeout=self.response_timeout
                    )
                    break
                except Exception:
                    continue

        # Phase 3 – poll until the response text has been stable for
        #            _STABILITY_DELAY_MS ms (handles streaming responses).
        last_text: str = ""
        stable_since: float = time.monotonic()

        while time.monotonic() < deadline:
            text = self._extract_last_response()
            if text != last_text:
                last_text = text
                stable_since = time.monotonic()
            elif text and (time.monotonic() - stable_since) * _MS >= _STABILITY_DELAY_MS:
                return text
            time.sleep(0.3)

        if last_text:
            return last_text
        raise RuntimeError(
            f"Timed out waiting for AI Studio response after {self.response_timeout / _MS:.0f} s."
        )

    def _extract_last_response(self) -> str:
        """Return the text of the latest model response, or an empty string."""
        page = self._page

        # Try CSS selectors first (fast path).
        for selector in _RESPONSE_SELECTORS:
            try:
                elements = page.query_selector_all(selector)
                if elements:
                    text = elements[-1].inner_text().strip()
                    if text:
                        return text
            except Exception:
                continue

        # JS fallback (resilient to component renames).
        try:
            text = page.evaluate(_RESPONSE_JS)
            if text:
                return text
        except Exception:
            pass

        return ""

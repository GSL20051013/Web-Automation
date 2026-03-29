"""
Google AI Studio browser client.

Automates https://aistudio.google.com/prompts/new_chat so that local servers
and personal apps can obtain AI responses without an API key.
"""

from __future__ import annotations

import sys
import time
from typing import Optional
from urllib.parse import urlparse

from .base import AIBrowserClient


# ---------------------------------------------------------------------------
# CSS / ARIA selectors for Google AI Studio
#
# AI Studio is an Angular SPA; its DOM structure changes over time.  Multiple
# fallback strategies are used throughout so that the client degrades
# gracefully rather than crashing on minor site updates.
# ---------------------------------------------------------------------------

# Prompt input – the editable area where the user types their message.
_INPUT_SELECTORS = [
    "ms-prompt-input rich-textarea .ql-editor",  # Quill-based rich text area
    "ms-prompt-input [contenteditable='true']",
    "ms-prompt-input textarea",
    ".prompt-input [contenteditable='true']",
    "[aria-label='Prompt input area']",
    "rich-textarea .ql-editor",
    "[data-testid='prompt-input']",
]

# Run / submit button.
_RUN_SELECTORS = [
    "run-button button:not([disabled])",
    "button[aria-label='Run']",
    "button[mattooltip='Run (Ctrl+Enter)']",
    "button:has-text('Run')",
]

# Indicator that a response is still being generated.
# AI Studio shows a stop button (or a spinner) while streaming.
_STOP_SELECTORS = [
    "button[aria-label='Stop']",
    "button[aria-label='Stop generation']",
    "button:has-text('Stop')",
    ".stop-button",
]

# Selector for the *last* model response turn in the conversation.
_RESPONSE_SELECTORS = [
    "ms-chat-turn[role='model']:last-of-type .chat-turn-content",
    "ms-chat-turn:last-of-type .model-response-text",
    ".model-response-text",
    "ms-text-chunk:last-of-type",
    ".chat-turn-container:last-child .model-response-text",
]

# Text that appears in the page title or a heading when AI Studio is ready.
_READY_MARKER = "AI Studio"

# Maximum time (ms) to wait for the response stream to complete.
_RESPONSE_TIMEOUT_MS = 180_000  # 3 minutes

# How long (ms) the response must be stable before we consider it complete.
_STABILITY_DELAY_MS = 2_000

# Milliseconds-to-seconds conversion factor.
_MS = 1_000.0

# Platform-aware modifier key: Command on macOS, Control everywhere else.
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
        current_url = page.url

        # Use urlparse so we check the actual hostname, not arbitrary substrings.
        parsed = urlparse(current_url)
        netloc = parsed.netloc.lower()
        path = parsed.path.lower()

        on_signin_page = (
            netloc == "accounts.google.com"
            or netloc.endswith(".accounts.google.com")
            or "signin" in path
        )

        # If we landed on a Google sign-in page, handle based on headless flag.
        if on_signin_page:
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
                "\n[ai_browser] A Google sign-in page was detected.\n"
                "Please log in to your Google account in the browser window that just opened.\n"
                "The script will continue automatically once you are signed in...\n"
            )
            # Wait up to 5 minutes for the user to complete sign-in.
            page.wait_for_url(
                "**/aistudio.google.com/**",
                timeout=300_000,
                wait_until="domcontentloaded",
            )
            print("[ai_browser] Sign-in detected – session saved. You can use headless=True from now on.\n")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _wait_for_page_ready(self) -> None:
        """Block until AI Studio's prompt input is visible and interactive."""
        page = self._page
        # Ensure the title matches AI Studio (not an error page / redirect).
        page.wait_for_function(
            "document.title.includes('AI Studio') || document.title.includes('Google AI')",
            timeout=self.timeout,
        )
        # Wait for at least one of the known input selectors to be present.
        for selector in _INPUT_SELECTORS:
            try:
                page.wait_for_selector(selector, state="visible", timeout=10_000)
                return
            except Exception:
                continue
        raise RuntimeError(
            "AI Studio prompt input not found.  The page may have changed its layout.\n"
            "Try running with headless=False to inspect the page, or file a bug report."
        )

    def _type_prompt(self, prompt: str) -> None:
        """Clear the input area and type *prompt*."""
        page = self._page
        input_el = None
        for selector in _INPUT_SELECTORS:
            try:
                el = page.wait_for_selector(selector, state="visible", timeout=5_000)
                if el:
                    input_el = el
                    break
            except Exception:
                continue

        if input_el is None:
            raise RuntimeError("Could not locate the prompt input area in AI Studio.")

        input_el.click()
        # Clear any existing text using a cross-platform JS approach, then
        # also try the select-all keyboard shortcut as a fallback.
        try:
            input_el.evaluate("el => { el.textContent = ''; }")
        except Exception:
            input_el.press(f"{_MOD}+a")
            input_el.press("Delete")
        # Use fill() for plain textareas; type() for contenteditable.
        try:
            input_el.fill(prompt)
        except Exception:
            input_el.type(prompt)

    def _submit_prompt(self) -> None:
        """Click the Run button (or fall back to Ctrl+Enter)."""
        page = self._page
        for selector in _RUN_SELECTORS:
            try:
                btn = page.wait_for_selector(selector, state="visible", timeout=5_000)
                if btn:
                    btn.click()
                    return
            except Exception:
                continue

        # Fallback: send the keyboard shortcut that AI Studio accepts.
        page.keyboard.press(f"{_MOD}+Return")

    def _wait_for_response(self) -> str:
        """Wait for the streaming response to finish and return the text."""
        page = self._page
        deadline = time.monotonic() + self.response_timeout / _MS

        # Phase 1: Wait for a stop/loading indicator to appear, confirming
        #          that generation has started.  We give it 15 seconds.
        generation_started = False
        for selector in _STOP_SELECTORS:
            try:
                page.wait_for_selector(selector, state="visible", timeout=15_000)
                generation_started = True
                break
            except Exception:
                continue

        # Phase 2: Wait for that indicator to disappear (generation complete).
        if generation_started:
            for selector in _STOP_SELECTORS:
                try:
                    page.wait_for_selector(selector, state="hidden", timeout=self.response_timeout)
                    break
                except Exception:
                    continue
        else:
            # The indicator may have appeared and disappeared very quickly;
            # fall through to the stability-based approach below.
            pass

        # Phase 3: Wait for the response text to stabilise.
        #          Poll until the text has not changed for _STABILITY_DELAY_MS.
        last_text: str = ""
        stable_since: float = time.monotonic()

        while time.monotonic() < deadline:
            text = self._extract_last_response()
            if text != last_text:
                last_text = text
                stable_since = time.monotonic()
            elif text and (time.monotonic() - stable_since) * _MS >= _STABILITY_DELAY_MS:
                # Text has been stable long enough – we are done.
                return text
            time.sleep(0.3)

        # Timeout – return whatever we have.
        if last_text:
            return last_text
        raise RuntimeError(
            f"Timed out waiting for AI Studio response after {self.response_timeout / _MS:.0f} s."
        )

    def _extract_last_response(self) -> str:
        """Return the text of the latest model response turn, or ''."""
        page = self._page
        for selector in _RESPONSE_SELECTORS:
            try:
                elements = page.query_selector_all(selector)
                if elements:
                    text = elements[-1].inner_text().strip()
                    if text:
                        return text
            except Exception:
                continue
        return ""

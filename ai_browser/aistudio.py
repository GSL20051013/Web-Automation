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
import re
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

# Prompt input area (textarea inside ms-prompt-box).
_INPUT_SELECTORS = [
    "ms-prompt-box textarea[aria-label='Enter a prompt']",
    "textarea[aria-label='Enter a prompt']",
    "ms-prompt-box .cdk-textarea-autosize",
    "ms-prompt-box textarea",
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
    "ms-run-button button[aria-label='Stop']",
]

# Last model-response container from which the reply text is extracted.
_RESPONSE_SELECTORS = [
    "ms-chat-turn[role='model']:last-of-type .chat-turn-content",
    "ms-chat-turn:last-of-type .model-response-text",
    ".model-response-text",
    "ms-text-chunk:last-of-type",
    "ms-chat-turn[role='model']:last-of-type",
]

# JavaScript fallback: return the last non-empty text found in a model turn.
_RESPONSE_JS = """
() => {
    const candidates = [
        ...document.querySelectorAll('ms-chat-turn[role="model"] .chat-turn-content'),
        ...document.querySelectorAll('.model-response-text'),
        ...document.querySelectorAll('ms-text-chunk'),
        ...document.querySelectorAll('ms-chat-turn[role="model"]'),
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

# Thinking level values accepted by set_thinking_level().
THINKING_LEVELS = ("None", "Low", "Medium", "High")


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

    def set_system_instructions(self, text: str) -> None:
        """Set the system instructions for the current chat session.

        Opens the System Instructions side-panel, clears any existing text,
        and types *text*.  Pass an empty string to clear the instructions.

        Parameters
        ----------
        text:
            The system instructions to apply (e.g. "You are a helpful pirate.").
        """
        if self._page is None:
            raise RuntimeError("Client is not started.")
        page = self._page

        # Open the system-instructions side panel.
        for selector in [
            "button[data-test-system-instructions-card]",
            "button[aria-label='System instructions']",
            ".system-instructions-card",
        ]:
            try:
                btn = page.wait_for_selector(selector, state="visible", timeout=5_000)
                if btn:
                    btn.click()
                    break
            except Exception:
                continue
        else:
            raise RuntimeError(
                "Could not find the System Instructions button. "
                "Run with headless=False to inspect the page."
            )

        # Wait for the panel to open and find the text input inside it.
        input_el = None
        for selector in [
            "ms-system-instructions-panel ms-sliding-right-panel textarea",
            "ms-system-instructions-panel textarea",
            "ms-sliding-right-panel textarea",
            "ms-sliding-right-panel [contenteditable='true']",
            "ms-sliding-right-panel .ql-editor",
        ]:
            try:
                input_el = page.wait_for_selector(selector, state="visible", timeout=8_000)
                if input_el:
                    break
            except Exception:
                continue

        if input_el is None:
            raise RuntimeError(
                "System instructions input area not found after opening the panel."
            )

        input_el.click()
        # For a regular <textarea>, fill() clears and sets text atomically.
        # For contenteditable elements, fill() is not supported, so we check
        # the element tag and choose the appropriate strategy.
        tag = input_el.evaluate("el => el.tagName.toLowerCase()")
        if tag == "textarea":
            input_el.fill(text)
        else:
            # Contenteditable: clear via select-all + delete, then type.
            input_el.press(f"{_MOD}+a")
            input_el.press("Delete")
            if text:
                input_el.type(text, delay=10)

    def set_temperature(self, value: float) -> None:
        """Set the model temperature (creativity / randomness).

        Parameters
        ----------
        value:
            A float in the range ``[0.0, 2.0]``.  Lower values make the
            model more deterministic; higher values make it more creative.
        """
        if self._page is None:
            raise RuntimeError("Client is not started.")
        if not 0.0 <= value <= 2.0:
            raise ValueError(f"Temperature must be between 0.0 and 2.0, got {value!r}.")

        page = self._page

        # Try to set the temperature slider via JavaScript (most reliable).
        set_js = f"""
        () => {{
            const containers = [
                document.querySelector('[data-test-id="temperatureSliderContainer"]'),
                ...document.querySelectorAll('ms-slider'),
            ];
            for (const c of containers) {{
                if (!c) continue;
                const input = c.querySelector('input[type="range"]');
                if (input) {{
                    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value').set;
                    nativeInputValueSetter.call(input, {value});
                    input.dispatchEvent(new Event('input', {{bubbles: true}}));
                    input.dispatchEvent(new Event('change', {{bubbles: true}}));
                    return true;
                }}
            }}
            return false;
        }}
        """
        result = page.evaluate(set_js)
        if not result:
            raise RuntimeError(
                "Could not locate the Temperature slider. "
                "Make sure the Run Settings panel is visible."
            )

    def set_thinking_level(self, level: str) -> None:
        """Set the model's thinking level.

        Parameters
        ----------
        level:
            One of ``"None"``, ``"Low"``, ``"Medium"``, or ``"High"``.
            Controls how much internal reasoning the model applies before
            generating its response (only available for supported models).
        """
        if self._page is None:
            raise RuntimeError("Client is not started.")
        # Normalise: accept "NONE", "none", "None", etc.
        level = level.title()
        if level not in THINKING_LEVELS:
            raise ValueError(
                f"level must be one of {THINKING_LEVELS}, got {level!r}."
            )

        page = self._page
        # level is now one of the fixed THINKING_LEVELS strings – safe to embed.
        level_lower = level.lower()

        # Click the Thinking Level combobox to open the dropdown.
        select_el = None
        for selector in [
            "mat-select[aria-label='Thinking Level']",
            "mat-select[aria-label='Thinking level']",
        ]:
            try:
                select_el = page.wait_for_selector(selector, state="visible", timeout=5_000)
                if select_el:
                    break
            except Exception:
                continue

        if select_el is None:
            raise RuntimeError(
                "Thinking Level selector not found. "
                "This setting may not be available for the current model."
            )

        select_el.click()

        # Wait for the dropdown panel and click the desired option.
        try:
            option = page.wait_for_selector(
                f"mat-option:has-text('{level}')",
                state="visible",
                timeout=5_000,
            )
            if option:
                option.click()
                return
        except Exception:
            pass

        # JS fallback: find the option by its text content.
        page.evaluate(
            """
            (levelLower) => {
                const options = document.querySelectorAll('mat-option');
                for (const o of options) {
                    if ((o.textContent || '').trim().toLowerCase() === levelLower) {
                        o.click();
                        return;
                    }
                }
            }
            """,
            level_lower,
        )

    def set_grounding(self, enabled: bool) -> None:
        """Enable or disable Grounding with Google Search.

        When enabled, the model can cite real-time web search results.

        Parameters
        ----------
        enabled:
            ``True`` to turn grounding on, ``False`` to turn it off.
        """
        if self._page is None:
            raise RuntimeError("Client is not started.")
        page = self._page

        # Find the grounding toggle switch.
        toggle = None
        for selector in [
            ".search-as-a-tool-toggle button[role='switch']",
            "mat-slide-toggle.search-as-a-tool-toggle button",
        ]:
            try:
                toggle = page.wait_for_selector(selector, state="visible", timeout=5_000)
                if toggle:
                    break
            except Exception:
                continue

        if toggle is None:
            raise RuntimeError(
                "Grounding with Google Search toggle not found. "
                "Make sure the Run Settings panel is visible."
            )

        # Read current state and click only if it needs to change.
        is_checked = toggle.get_attribute("aria-checked") == "true"
        if is_checked != enabled:
            toggle.click()

    def get_token_count(self) -> Optional[int]:
        """Return the current token count shown in the UI, or ``None``.

        AI Studio displays a running token count while you compose a prompt.
        This method reads that value and returns it as an integer.

        Returns
        -------
        int or None
            The token count, or ``None`` if the counter is not visible /
            cannot be parsed.
        """
        if self._page is None:
            raise RuntimeError("Client is not started.")
        page = self._page

        try:
            el = page.query_selector("ms-token-count")
            if el is None:
                return None
            raw = el.inner_text().strip()
            # Extract the first sequence of digits (e.g. "1,234 tokens" → 1234).
            parts = raw.split()
            digits = re.sub(r"[^\d]", "", parts[0]) if parts else ""
            return int(digits) if digits else None
        except Exception:
            return None

    def upload_file(self, path: str) -> None:
        """Attach a local file (image, video, audio, or document) to the prompt.

        Parameters
        ----------
        path:
            Absolute or relative path to the file to upload.
        """
        if self._page is None:
            raise RuntimeError("Client is not started.")
        if not os.path.isfile(path):
            raise FileNotFoundError(f"File not found: {path!r}")

        page = self._page

        # Click the media-attachment button to open a file chooser.
        media_btn = None
        for selector in [
            "button[aria-label='Insert images, videos, audio, or files']",
            "ms-add-media-button button",
            "button[aria-label*='Insert']",
        ]:
            try:
                media_btn = page.wait_for_selector(selector, state="visible", timeout=5_000)
                if media_btn:
                    break
            except Exception:
                continue

        if media_btn is None:
            raise RuntimeError(
                "Could not find the media-attachment button in AI Studio."
            )

        with page.expect_file_chooser(timeout=10_000) as fc_info:
            media_btn.click()
        fc_info.value.set_files(os.path.abspath(path))

    # ------------------------------------------------------------------
    # Tool use
    # ------------------------------------------------------------------

    def set_code_execution(self, enabled: bool) -> None:
        """Enable or disable the Code Execution tool.

        When enabled, the model can write and run Python code during
        inference to solve problems that benefit from computation.

        Parameters
        ----------
        enabled:
            ``True`` to turn code execution on, ``False`` to turn it off.
        """
        if self._page is None:
            raise RuntimeError("Client is not started.")
        self._ensure_tools_expanded()
        self._toggle_tool_switch(
            enabled=enabled,
            selectors=[
                ".code-execution-toggle button[role='switch']",
                "mat-slide-toggle.code-execution-toggle button",
                "button[aria-label='Code execution']",
            ],
            error_msg=(
                "Code Execution toggle not found. "
                "Make sure the Run Settings panel is visible."
            ),
        )

    def set_function_calling(self, enabled: bool) -> None:
        """Enable or disable the Function Calling tool.

        When enabled, the model can invoke the function declarations you
        have defined instead of (or in addition to) generating text.

        Parameters
        ----------
        enabled:
            ``True`` to turn function calling on, ``False`` to turn it off.

        See Also
        --------
        set_function_declarations : Define the callable functions.
        """
        if self._page is None:
            raise RuntimeError("Client is not started.")
        self._ensure_tools_expanded()
        self._toggle_tool_switch(
            enabled=enabled,
            selectors=[
                ".function-calling-toggle button[role='switch']",
                "mat-slide-toggle.function-calling-toggle button",
                "button[aria-label='Function calling']",
            ],
            error_msg=(
                "Function Calling toggle not found. "
                "Make sure the Run Settings panel is visible."
            ),
        )

    def set_function_declarations(self, json_text: str) -> None:
        """Define the functions the model may call (function calling / tool use).

        Enables the Function Calling toggle (if not already on), opens the
        function-declarations editor, replaces the content with *json_text*,
        and saves.

        The expected format is a JSON array of ``FunctionDeclaration`` objects
        as described in the `Gemini API reference
        <https://ai.google.dev/api/generate-content#v1beta.FunctionDeclaration>`_::

            [
              {
                "name": "get_weather",
                "description": "Return current weather for a city.",
                "parameters": {
                  "type": "object",
                  "properties": {
                    "city": {"type": "string", "description": "City name"}
                  },
                  "required": ["city"]
                }
              }
            ]

        Parameters
        ----------
        json_text:
            A JSON string containing an array of FunctionDeclaration objects.

        Raises
        ------
        ValueError
            If *json_text* is not valid JSON.
        RuntimeError
            If the editor panel cannot be found.
        """
        import json as _json

        if self._page is None:
            raise RuntimeError("Client is not started.")

        try:
            _json.loads(json_text)
        except _json.JSONDecodeError as exc:
            raise ValueError(f"json_text is not valid JSON: {exc}") from exc

        # Ensure function calling is enabled first.
        self.set_function_calling(True)

        page = self._page

        # Click the "Edit" button next to the Function Calling toggle.
        edit_btn = None
        for selector in [
            "button[aria-label='Edit function declarations']",
            ".edit-function-declarations-button",
        ]:
            try:
                edit_btn = page.wait_for_selector(selector, state="visible", timeout=5_000)
                if edit_btn:
                    break
            except Exception:
                continue

        if edit_btn is None:
            raise RuntimeError(
                "Edit function declarations button not found. "
                "Make sure Function Calling is enabled and the Run Settings panel is visible."
            )
        edit_btn.click()

        # Wait for the editor panel / dialog to open and find its textarea.
        editor = self._wait_for_json_editor()
        self._fill_json_editor(editor, json_text)

    def set_structured_output(self, enabled: bool) -> None:
        """Enable or disable Structured Outputs.

        When enabled, the model returns a response conforming to the JSON
        schema you specify with :meth:`set_structured_output_schema`.

        Parameters
        ----------
        enabled:
            ``True`` to turn structured output on, ``False`` to turn it off.

        See Also
        --------
        set_structured_output_schema : Provide the JSON schema.
        """
        if self._page is None:
            raise RuntimeError("Client is not started.")
        self._ensure_tools_expanded()
        self._toggle_tool_switch(
            enabled=enabled,
            selectors=[
                ".structured-output-toggle button[role='switch']",
                "mat-slide-toggle.structured-output-toggle button",
                "button[aria-label='Structured outputs']",
            ],
            error_msg=(
                "Structured Outputs toggle not found. "
                "Make sure the Run Settings panel is visible."
            ),
        )

    def set_structured_output_schema(self, json_text: str) -> None:
        """Provide the JSON schema for structured output.

        Enables the Structured Outputs toggle (if not already on), opens
        the schema editor, replaces the content with *json_text*, and saves.

        The expected format is a JSON Schema object, e.g.::

            {
              "type": "object",
              "properties": {
                "answer": {"type": "string"},
                "confidence": {"type": "number"}
              },
              "required": ["answer"]
            }

        Parameters
        ----------
        json_text:
            A JSON string containing the response schema.

        Raises
        ------
        ValueError
            If *json_text* is not valid JSON.
        RuntimeError
            If the editor panel cannot be found.
        """
        import json as _json

        if self._page is None:
            raise RuntimeError("Client is not started.")

        try:
            _json.loads(json_text)
        except _json.JSONDecodeError as exc:
            raise ValueError(f"json_text is not valid JSON: {exc}") from exc

        # Ensure structured output is enabled first.
        self.set_structured_output(True)

        page = self._page

        # Click the "Edit JSON schema" button.
        edit_btn = None
        for selector in [
            "button[aria-label='Edit JSON schema']",
            "button[data-test-id='editJsonSchemaButton']",
            ".edit-schema-button",
        ]:
            try:
                edit_btn = page.wait_for_selector(selector, state="visible", timeout=5_000)
                if edit_btn:
                    break
            except Exception:
                continue

        if edit_btn is None:
            raise RuntimeError(
                "Edit JSON schema button not found. "
                "Make sure Structured Outputs is enabled and the Run Settings panel is visible."
            )
        edit_btn.click()

        editor = self._wait_for_json_editor()
        self._fill_json_editor(editor, json_text)

    def set_url_context(self, enabled: bool) -> None:
        """Enable or disable the URL Context tool.

        When enabled, the model can fetch and read the content of URLs
        that appear in the prompt.

        Parameters
        ----------
        enabled:
            ``True`` to turn URL context on, ``False`` to turn it off.
        """
        if self._page is None:
            raise RuntimeError("Client is not started.")
        self._ensure_tools_expanded()
        self._toggle_tool_switch(
            enabled=enabled,
            selectors=[
                "button[aria-label='Browse the url context']",
                ".url-context-toggle button[role='switch']",
                "mat-slide-toggle.url-context-toggle button",
            ],
            error_msg=(
                "URL Context toggle not found. "
                "Make sure the Run Settings panel is visible."
            ),
        )

    def set_maps_grounding(self, enabled: bool) -> None:
        """Enable or disable Grounding with Google Maps.

        When enabled, the model can reference real-time map data (e.g.
        business details, directions) via Google Maps.

        Parameters
        ----------
        enabled:
            ``True`` to turn Maps grounding on, ``False`` to turn it off.
        """
        if self._page is None:
            raise RuntimeError("Client is not started.")
        self._ensure_tools_expanded()
        self._toggle_tool_switch(
            enabled=enabled,
            selectors=[
                ".google-maps-toggle button[role='switch']",
                "mat-slide-toggle.google-maps-toggle button",
                "button[aria-label='Grounding with Google Maps']",
            ],
            error_msg=(
                "Grounding with Google Maps toggle not found. "
                "Make sure the Run Settings panel is visible."
            ),
        )

    # ------------------------------------------------------------------
    # Tool-use helpers (private)
    # ------------------------------------------------------------------

    def _ensure_tools_expanded(self) -> None:
        """Expand the Tools section in the Run Settings panel if it is collapsed.

        The Tools section has a toggle button whose icon changes between
        ``expand_more`` (collapsed) and ``expand_less`` (expanded).  We click
        the button only when the section is not yet expanded.
        """
        page = self._page
        for selector in [
            "button[aria-label='Expand or collapse tools']",
            ".expand-icon[aria-label='Expand or collapse tools']",
        ]:
            try:
                btn = page.wait_for_selector(selector, state="visible", timeout=5_000)
                if btn:
                    # The section is expanded when the icon text is "expand_less".
                    icon_text = btn.inner_text().strip()
                    if "expand_more" in icon_text:
                        btn.click()
                        time.sleep(0.3)
                    return
            except Exception:
                continue

    def _toggle_tool_switch(
        self,
        enabled: bool,
        selectors: list,
        error_msg: str,
    ) -> None:
        """Find a toggle switch by *selectors* and set it to *enabled*.

        Parameters
        ----------
        enabled:
            Desired state of the toggle.
        selectors:
            Ordered list of CSS selectors to try.
        error_msg:
            Message for the ``RuntimeError`` raised when the toggle cannot
            be located.
        """
        page = self._page
        toggle = None
        for selector in selectors:
            try:
                toggle = page.wait_for_selector(selector, state="visible", timeout=5_000)
                if toggle:
                    break
            except Exception:
                continue

        if toggle is None:
            raise RuntimeError(error_msg)

        is_checked = toggle.get_attribute("aria-checked") == "true"
        if is_checked != enabled:
            toggle.click()

    def _wait_for_json_editor(self) -> Any:
        """Wait for a JSON editor panel/dialog to open and return its textarea.

        Tries a prioritised list of selectors that are known to be used by
        AI Studio's function-declaration and JSON-schema editors.

        Returns
        -------
        Playwright element handle for the editor textarea / contenteditable.

        Raises
        ------
        RuntimeError
            If no editor is found within the timeout.
        """
        page = self._page
        for selector in [
            "ms-sliding-right-panel textarea",
            "ms-sliding-right-panel [contenteditable='true']",
            "ms-sliding-right-panel .ql-editor",
            ".function-declarations-editor textarea",
            ".json-editor textarea",
            "mat-dialog-container textarea",
            "mat-dialog-container [contenteditable='true']",
            "mat-dialog-container .ql-editor",
        ]:
            try:
                el = page.wait_for_selector(selector, state="visible", timeout=8_000)
                if el:
                    return el
            except Exception:
                continue

        raise RuntimeError(
            "JSON editor panel not found. "
            "Run with headless=False to inspect the page."
        )

    def _fill_json_editor(self, editor: Any, json_text: str) -> None:
        """Clear *editor* and fill it with *json_text*, then save/close.

        Parameters
        ----------
        editor:
            Playwright element handle for the editor textarea / contenteditable.
        json_text:
            The JSON text to insert.
        """
        page = self._page
        editor.click()
        tag = editor.evaluate("el => el.tagName.toLowerCase()")
        if tag == "textarea":
            editor.fill(json_text)
        else:
            editor.press(f"{_MOD}+a")
            editor.press("Delete")
            if json_text:
                editor.type(json_text, delay=2)

        # Try to confirm / save via a Save or Apply button; fall back to Escape.
        for selector in [
            "button[aria-label='Save']",
            "button:has-text('Save')",
            "button:has-text('Apply')",
            "button:has-text('Done')",
        ]:
            try:
                btn = page.query_selector(selector)
                if btn and btn.is_visible():
                    btn.click()
                    return
            except Exception:
                continue

        # No explicit save button – close the panel with Escape.
        page.keyboard.press("Escape")

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

        # For a regular <textarea>, fill() clears the existing text and sets
        # the new value atomically.  For contenteditable, fill() is not
        # supported, so we fall back to a select-all + type sequence.
        try:
            input_el.fill(prompt)
        except Exception:
            # Contenteditable fallback: clear via JS, then type character by
            # character so that Angular's change-detection fires properly.
            try:
                input_el.evaluate("el => { el.textContent = ''; }")
            except Exception:
                input_el.press(f"{_MOD}+a")
                input_el.press("Delete")
            input_el.type(prompt, delay=10)

    def _submit_prompt(self) -> None:
        """Submit the prompt.

        Tries the Run button (``ms-run-button``) first because it is the most
        reliable target on the current UI.  Falls back to ``Ctrl+Enter``
        (``Cmd+Enter`` on macOS) which is a stable keyboard shortcut that
        works regardless of button-layout changes.
        """
        page = self._page

        # Quick, non-blocking check for a visible Run button.
        for selector in [
            "ms-run-button button[type='submit']",
            "ms-run-button button",
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

        # Fallback: keyboard shortcut.
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

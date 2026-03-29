"""Base class for AI browser clients."""

import abc
import os
from pathlib import Path
from typing import Optional


class AIBrowserClient(abc.ABC):
    """
    Abstract base class for AI browser clients.

    Subclasses automate specific AI websites via a headless browser so that
    local servers and personal apps can obtain AI responses without any API key.

    Usage (context-manager, recommended)::

        with MyAIClient(headless=True) as client:
            response = client.chat("Hello, world!")
            print(response)

    Usage (manual lifecycle)::

        client = MyAIClient(headless=False)
        client.start()
        response = client.chat("Hello, world!")
        client.stop()
    """

    #: Override in subclasses with the default URL to open when starting.
    DEFAULT_URL: str = ""

    def __init__(
        self,
        headless: bool = True,
        profile_dir: Optional[str] = None,
        timeout: int = 60_000,
    ) -> None:
        """
        Parameters
        ----------
        headless:
            Run the browser without a visible window (default ``True``).
            Set to ``False`` to watch the browser or to log in for the first
            time.
        profile_dir:
            Path to a directory used to persist the browser profile (cookies,
            local storage, etc.) between runs.  Defaults to
            ``~/.ai_browser/<class-name>/``.
        timeout:
            Default navigation / element-wait timeout in milliseconds
            (default 60 000 ms = 60 s).
        """
        self.headless = headless
        self.profile_dir = profile_dir or str(
            Path.home() / ".ai_browser" / type(self).__name__
        )
        self.timeout = timeout

        self._playwright = None
        self._context = None
        self._page = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> "AIBrowserClient":
        """Launch the browser and navigate to the AI site.

        Returns *self* so the call can be chained::

            client = MyAIClient().start()
        """
        from playwright.sync_api import sync_playwright  # lazy import

        os.makedirs(self.profile_dir, exist_ok=True)

        self._playwright = sync_playwright().start()
        self._context = self._playwright.firefox.launch_persistent_context(
            self.profile_dir,
            headless=self.headless,
            viewport={"width": 1280, "height": 900},
        )

        # Reuse the existing page if one is already open (persistent context
        # may have restored previous session tabs).
        if self._context.pages:
            self._page = self._context.pages[0]
        else:
            self._page = self._context.new_page()

        self._page.set_default_timeout(self.timeout)
        self._on_start()
        return self

    def stop(self) -> None:
        """Close the browser and release all resources."""
        try:
            if self._context is not None:
                self._context.close()
        finally:
            if self._playwright is not None:
                self._playwright.stop()
            self._context = None
            self._page = None
            self._playwright = None

    # ------------------------------------------------------------------
    # Context-manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> "AIBrowserClient":
        return self.start()

    def __exit__(self, *_exc) -> None:
        self.stop()

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def chat(self, prompt: str) -> str:
        """Send *prompt* and return the AI's response as plain text.

        Parameters
        ----------
        prompt:
            The text to send to the AI.

        Returns
        -------
        str
            The AI's response text.
        """

    @abc.abstractmethod
    def new_chat(self) -> None:
        """Navigate to a fresh, empty chat session."""

    # ------------------------------------------------------------------
    # Internal helpers (may be overridden by subclasses)
    # ------------------------------------------------------------------

    def _on_start(self) -> None:
        """Called by :meth:`start` after the browser is ready.

        Default behaviour: navigate to :attr:`DEFAULT_URL` and check login.
        Override for custom startup logic.
        """
        if self.DEFAULT_URL:
            self._page.goto(
                self.DEFAULT_URL,
                timeout=self.timeout,
                wait_until="domcontentloaded",
            )
        self._ensure_logged_in()

    def _ensure_logged_in(self) -> None:
        """Raise or wait for the user to log in, depending on *headless* mode.

        Override in subclasses to detect the login page for a specific site.
        """

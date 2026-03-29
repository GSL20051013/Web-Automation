"""ai_browser – Use AI websites without an API key via browser automation."""

from .aistudio import THINKING_LEVELS, AIStudio
from .base import AIBrowserClient

__all__ = ["AIBrowserClient", "AIStudio", "THINKING_LEVELS"]

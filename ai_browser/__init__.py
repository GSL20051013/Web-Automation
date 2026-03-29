"""ai_browser – Use AI websites without an API key via browser automation."""

from .aistudio import AIStudio
from .base import AIBrowserClient

__all__ = ["AIBrowserClient", "AIStudio"]

"""Generic OpenAI-compatible provider (any /v1/chat/completions endpoint)."""

from providers.openai_compat_provider.client import OpenAICompatProvider

__all__ = ["OpenAICompatProvider"]

"""Generic OpenAI-compatible provider.

Connects to any /v1/chat/completions endpoint (LM Studio, vLLM, Ollama OpenAI
mode, LocalAI, etc.) using the same OpenAI chat transport as NVIDIA NIM.

Config env vars:
    OPENAI_COMPAT_BASE_URL  Base URL of the endpoint (e.g. http://192.168.11.13:1234/v1)
    OPENAI_COMPAT_API_KEY   API key (use any non-empty string for keyless endpoints)
"""

from typing import Any

from providers.base import ProviderConfig
from providers.openai_compat import OpenAIChatTransport

_OPENAI_COMPAT_DEFAULT_BASE = "http://localhost:1234/v1"


class OpenAICompatProvider(OpenAIChatTransport):
    """Generic OpenAI-compatible provider using /v1/chat/completions."""

    def __init__(self, config: ProviderConfig):
        super().__init__(
            config,
            provider_name="OPENAI_COMPAT",
            base_url=config.base_url or _OPENAI_COMPAT_DEFAULT_BASE,
            api_key=config.api_key or "openai-compat",
        )

    def _build_request_body(
        self, request: Any, thinking_enabled: bool | None = None
    ) -> dict:
        """Build a plain OpenAI chat completions request body."""
        from core.anthropic.conversion import build_base_request_body

        return build_base_request_body(request)

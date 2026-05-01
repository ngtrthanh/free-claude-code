"""Xiaomi MiMo provider — native Anthropic Messages endpoint."""

from providers.anthropic_messages import AnthropicMessagesTransport
from providers.base import ProviderConfig

XIAOMI_DEFAULT_BASE = "https://api.xiaomimimo.com/anthropic/v1"


class XiaomiProvider(AnthropicMessagesTransport):
    """Xiaomi MiMo via native Anthropic Messages at api.xiaomimimo.com/anthropic."""

    def __init__(self, config: ProviderConfig):
        super().__init__(
            config,
            provider_name="XIAOMI",
            default_base_url=XIAOMI_DEFAULT_BASE,
        )

    def _request_headers(self) -> dict[str, str]:
        """Include x-api-key and anthropic-version for Xiaomi's Anthropic endpoint."""
        return {
            "Content-Type": "application/json",
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
        }

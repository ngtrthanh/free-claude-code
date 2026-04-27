"""Model routing for Claude-compatible requests."""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

from config.settings import Settings

from .models.anthropic import MessagesRequest, TokenCountRequest

# Cortex virtual model prefix — these bypass normal provider/model resolution
_CORTEX_PREFIX = "cortex-"
_CORTEX_TIER_MAP = {
    "cortex-auto": "auto",
    "cortex-local": "local",
    "cortex-remote": "remote",
    "cortex-smart": "smart",
    "cortex-native": "native",
}


@dataclass(frozen=True, slots=True)
class ResolvedModel:
    original_model: str
    provider_id: str
    provider_model: str
    provider_model_ref: str
    thinking_enabled: bool
    cortex_tier_hint: str | None = None  # set when a cortex-* virtual model is used


@dataclass(frozen=True, slots=True)
class RoutedMessagesRequest:
    request: MessagesRequest
    resolved: ResolvedModel


@dataclass(frozen=True, slots=True)
class RoutedTokenCountRequest:
    request: TokenCountRequest
    resolved: ResolvedModel


class ModelRouter:
    """Resolve incoming Claude model names to configured provider/model pairs."""

    def __init__(self, settings: Settings):
        self._settings = settings

    def resolve(self, claude_model_name: str) -> ResolvedModel:
        # Handle cortex-* virtual model names
        if claude_model_name.startswith(_CORTEX_PREFIX):
            tier = _CORTEX_TIER_MAP.get(claude_model_name, "auto")
            logger.debug("CORTEX: virtual model {} → tier {}", claude_model_name, tier)
            return ResolvedModel(
                original_model=claude_model_name,
                provider_id="cortex",
                provider_model=claude_model_name,  # passed through; cortex ignores it
                provider_model_ref=f"cortex/{claude_model_name}",
                thinking_enabled=self._settings.resolve_thinking(claude_model_name),
                cortex_tier_hint=tier,
            )

        provider_model_ref = self._settings.resolve_model(claude_model_name)
        thinking_enabled = self._settings.resolve_thinking(claude_model_name)
        provider_id = Settings.parse_provider_type(provider_model_ref)
        provider_model = Settings.parse_model_name(provider_model_ref)
        if provider_model != claude_model_name:
            logger.debug(
                "MODEL MAPPING: '{}' -> '{}'", claude_model_name, provider_model
            )
        return ResolvedModel(
            original_model=claude_model_name,
            provider_id=provider_id,
            provider_model=provider_model,
            provider_model_ref=provider_model_ref,
            thinking_enabled=thinking_enabled,
            cortex_tier_hint=None,
        )

    def resolve_messages_request(
        self, request: MessagesRequest
    ) -> RoutedMessagesRequest:
        """Return an internal routed request context."""
        resolved = self.resolve(request.model)
        routed = request.model_copy(deep=True)
        routed.model = resolved.provider_model
        return RoutedMessagesRequest(request=routed, resolved=resolved)

    def resolve_token_count_request(
        self, request: TokenCountRequest
    ) -> RoutedTokenCountRequest:
        """Return an internal token-count request context."""
        resolved = self.resolve(request.model)
        routed = request.model_copy(
            update={"model": resolved.provider_model}, deep=True
        )
        return RoutedTokenCountRequest(request=routed, resolved=resolved)

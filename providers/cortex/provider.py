"""CortexProvider — smart routing provider.

Routes each request to the best available provider based on complexity score.
Falls back through tiers on error. Supports explicit brain override via
a process-level state variable set by the /v1/cortex/brain endpoint.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from loguru import logger

from providers.base import BaseProvider, ProviderConfig
from providers.cortex.scorer import score_request
from providers.cortex.tiers import TierConfig
from providers.exceptions import ProviderError

# Process-level brain override: set by POST /v1/cortex/brain
# None = auto (score-based), otherwise a tier name or provider/model string
_brain_override: str | None = None
_brain_lock = asyncio.Lock()


def get_brain_override() -> str | None:
    """Return the current brain override (tier name or provider/model)."""
    return _brain_override


def _set_brain_override_sync(value: str | None) -> None:
    """Set the brain override synchronously (no lock — called from sync service layer)."""
    global _brain_override
    _brain_override = value
    logger.info("CORTEX: brain override set to {!r} (sync)", value)


async def set_brain_override(value: str | None) -> None:
    """Set the brain override. Pass None to restore auto-routing."""
    global _brain_override
    async with _brain_lock:
        _brain_override = value
    logger.info("CORTEX: brain override set to {!r}", value)


class CortexProvider(BaseProvider):
    """Smart routing provider that dispatches to the right backend by complexity.

    Does not hold its own HTTP client — delegates entirely to sub-providers
    obtained via the provider_getter callable (same as the registry pattern).
    """

    def __init__(
        self,
        config: ProviderConfig,
        tier_config: TierConfig,
        provider_getter: Any,  # Callable[[str, Settings], BaseProvider]
        settings: Any,  # Settings
    ):
        super().__init__(config)
        self._tier_config = tier_config
        self._provider_getter = provider_getter
        self._settings = settings

    async def cleanup(self) -> None:
        """Nothing to clean up — sub-providers are managed by the registry."""

    def _resolve_candidates(
        self, request: Any, input_tokens: int
    ) -> list[tuple[str, str]]:
        """Return ordered list of (provider_id, model_name) candidates to try.

        Respects brain override if set.
        """
        from config.settings import Settings

        override = get_brain_override()

        if override is not None:
            # Override can be a tier name ("local", "smart") or a full "provider/model"
            if override in self._tier_config.models:
                # It's a tier name
                models = self._tier_config.models_for_tier(override)
            elif "/" in override:
                # It's a direct provider/model string
                models = [override]
            else:
                logger.warning(
                    "CORTEX: unknown brain override {!r}, using auto", override
                )
                models = []

            if models:
                return [
                    (Settings.parse_provider_type(m), Settings.parse_model_name(m))
                    for m in models
                ]

        # Auto: score the request and get tier order
        score = score_request(request, input_tokens)
        tiers = self._tier_config.tiers_for_score(score)

        logger.debug(
            "CORTEX: score={} tiers={} model={}",
            score,
            tiers,
            getattr(request, "model", "?"),
        )

        candidates: list[tuple[str, str]] = []
        for tier in tiers:
            for model_ref in self._tier_config.models_for_tier(tier):
                provider_id = Settings.parse_provider_type(model_ref)
                model_name = Settings.parse_model_name(model_ref)
                candidates.append((provider_id, model_name))

        return candidates

    async def stream_response(
        self,
        request: Any,
        input_tokens: int = 0,
        *,
        request_id: str | None = None,
        thinking_enabled: bool | None = None,
    ) -> AsyncIterator[str]:
        """Try each candidate provider in order, yielding from the first that works."""

        candidates = self._resolve_candidates(request, input_tokens)

        if not candidates:
            raise ProviderError(
                "Cortex has no providers configured. "
                "Set CORTEX_LOCAL_MODELS, CORTEX_SMART_MODELS, etc. in your .env"
            )

        last_error: Exception | None = None

        for provider_id, model_name in candidates:
            # Patch the model name on a copy of the request
            patched = request.model_copy(update={"model": model_name}, deep=False)

            try:
                provider = self._provider_getter(provider_id)
                logger.info(
                    "CORTEX: trying provider={} model={} request_id={}",
                    provider_id,
                    model_name,
                    request_id,
                )
                async for chunk in provider.stream_response(
                    patched,
                    input_tokens=input_tokens,
                    request_id=request_id,
                    thinking_enabled=thinking_enabled,
                ):
                    yield chunk
                return  # success — done

            except Exception as e:
                last_error = e
                logger.warning(
                    "CORTEX: provider={} model={} failed ({}), trying next",
                    provider_id,
                    model_name,
                    type(e).__name__,
                )
                continue

        # All candidates exhausted
        assert last_error is not None
        raise last_error

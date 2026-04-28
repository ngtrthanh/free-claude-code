"""CortexProvider — smart routing provider.

Routes each request to the best available provider based on complexity score.
Falls back through tiers on error. Supports explicit brain override via
a process-level state variable set by the /v1/cortex/brain endpoint.

Circuit breaker: providers that fail with connection errors are cooled down
for CIRCUIT_COOLDOWN_S seconds before being retried, avoiding repeated
timeouts on unreachable local endpoints.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

from loguru import logger

from providers.base import BaseProvider, ProviderConfig
from providers.cortex.scorer import score_request
from providers.cortex.tiers import TierConfig
from providers.exceptions import ProviderError

# Process-level brain override
_brain_override: str | None = None
_brain_lock = asyncio.Lock()

# Circuit breaker: provider_id → timestamp when it can be retried
# Keyed by "provider_id/model_name" for per-model granularity
_circuit_open_until: dict[str, float] = {}
_circuit_lock = asyncio.Lock()

# How long to skip a provider after a connection failure (seconds)
CIRCUIT_COOLDOWN_S = 60.0

# Errors that trip the circuit (connectivity issues, not logic errors)
_CIRCUIT_TRIP_ERRORS = (
    "ConnectTimeout",
    "ConnectError",
    "TimeoutError",
    "ConnectionError",
    "RemoteProtocolError",
)


def get_brain_override() -> str | None:
    """Return the current brain override (tier name or provider/model)."""
    return _brain_override


def _get_current_client() -> str:
    """Return the current request's client identifier (set by the HTTP layer)."""
    try:
        from core.request_context import current_client

        return current_client.get()
    except Exception:
        return "unknown"


def _set_brain_override_sync(value: str | None) -> None:
    """Set the brain override synchronously (no lock — called from sync service layer)."""
    global _brain_override
    _brain_override = value
    logger.info("CORTEX: brain override set to {!r} (sync)", value)
    # Push to metrics (best-effort, no await in sync context)
    try:
        from core.cortex_metrics import CortexMetrics
        import asyncio

        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(CortexMetrics.get().update_brain(value))
    except Exception:
        pass


async def set_brain_override(value: str | None) -> None:
    """Set the brain override. Pass None to restore auto-routing."""
    global _brain_override
    async with _brain_lock:
        _brain_override = value
    logger.info("CORTEX: brain override set to {!r}", value)
    from core.cortex_metrics import CortexMetrics

    await CortexMetrics.get().update_brain(value)


def _circuit_key(provider_id: str, model_name: str) -> str:
    return f"{provider_id}/{model_name}"


def _is_circuit_open(provider_id: str, model_name: str) -> bool:
    """Return True if this provider/model is in cooldown."""
    key = _circuit_key(provider_id, model_name)
    until = _circuit_open_until.get(key, 0.0)
    if until > time.monotonic():
        return True
    if key in _circuit_open_until:
        del _circuit_open_until[key]
    return False


def _trip_circuit(provider_id: str, model_name: str, error: Exception) -> None:
    """Open the circuit for this provider/model if the error is connectivity-related."""
    err_type = type(error).__name__
    if any(t in err_type for t in _CIRCUIT_TRIP_ERRORS):
        key = _circuit_key(provider_id, model_name)
        _circuit_open_until[key] = time.monotonic() + CIRCUIT_COOLDOWN_S
        logger.warning(
            "CORTEX: circuit opened for {}/{} ({}) — skipping for {}s",
            provider_id,
            model_name,
            err_type,
            CIRCUIT_COOLDOWN_S,
        )


def get_circuit_status() -> dict[str, float]:
    """Return remaining cooldown seconds per provider/model key."""
    now = time.monotonic()
    return {k: round(v - now, 1) for k, v in _circuit_open_until.items() if v > now}


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
        from core.cortex_metrics import CortexMetrics
        from providers.cortex.scorer import TIER_LOCAL

        candidates = self._resolve_candidates(request, input_tokens)

        if not candidates:
            raise ProviderError(
                "Cortex has no providers configured. "
                "Set CORTEX_LOCAL_MODELS, CORTEX_SMART_MODELS, etc. in your .env"
            )

        metrics = CortexMetrics.get()
        last_error: Exception | None = None
        fallback_count = 0
        req_id = request_id or "unknown"

        # Determine tier for the first candidate
        from providers.cortex.scorer import score_request, score_to_tier

        score = score_request(request, input_tokens)
        override = get_brain_override()
        if override and override in self._tier_config.models:
            tier = override
        elif override and "/" in override:
            tier = "direct"
        else:
            tier = score_to_tier(score, self._tier_config.thresholds)

        for provider_id, model_name in candidates:
            # Skip if circuit is open (recent connection failure)
            if _is_circuit_open(provider_id, model_name):
                logger.debug(
                    "CORTEX: skipping {}/{} — circuit open",
                    provider_id,
                    model_name,
                )
                fallback_count += 1
                tier = "fallback"
                continue

            # Patch the model name on a copy of the request
            patched = request.model_copy(update={"model": model_name}, deep=False)

            try:
                provider = self._provider_getter(provider_id)
                logger.info(
                    "CORTEX: trying provider={} model={} request_id={}",
                    provider_id,
                    model_name,
                    req_id,
                )

                # Record start
                await metrics.request_started(
                    request_id=req_id,
                    model=getattr(request, "model", "unknown"),
                    provider_id=provider_id,
                    provider_model=model_name,
                    tier=tier,
                    score=score,
                    input_tokens=input_tokens,
                    client=_get_current_client(),
                )

                try:
                    async for chunk in provider.stream_response(
                        patched,
                        input_tokens=input_tokens,
                        request_id=req_id,
                        thinking_enabled=thinking_enabled,
                    ):
                        # Count output tokens from text_delta events
                        if '"text_delta"' in chunk or '"thinking_delta"' in chunk:
                            await metrics.token_emitted(req_id)
                        yield chunk

                    await metrics.request_finished(
                        req_id, success=True, fallback_count=fallback_count
                    )
                    return  # success — done

                except Exception as e:
                    _trip_circuit(provider_id, model_name, e)
                    await metrics.request_finished(
                        req_id, success=False, fallback_count=fallback_count
                    )
                    raise e

            except Exception as e:
                last_error = e
                fallback_count += 1
                tier = "fallback"  # mark subsequent attempts as fallback
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

"""Tier configuration for Cortex routing.

Each tier maps to an ordered list of provider/model strings.
Cortex tries them in order, falling back on any error.

Env vars
--------
CORTEX_LOCAL_MODELS   = "lmstudio/gemma-4-E4B-it-MLX-8bit,ollama/llama3"
CORTEX_REMOTE_MODELS  = "open_router/meta-llama/llama-3.1-8b-instruct:free"
CORTEX_SMART_MODELS   = "nvidia_nim/deepseek-ai/deepseek-v4-pro,open_router/anthropic/claude-sonnet-4"
CORTEX_NATIVE_MODELS  = "open_router/anthropic/claude-opus-4"

CORTEX_THRESHOLD_LOCAL  = 0    (score >= 0  → eligible for local)
CORTEX_THRESHOLD_REMOTE = 25   (score >= 25 → use remote instead of local)
CORTEX_THRESHOLD_SMART  = 55   (score >= 55 → use smart)
CORTEX_THRESHOLD_NATIVE = 85   (score >= 85 → use native)

CORTEX_FALLBACK_ASCENDING = true   (on error, try next tier up)
CORTEX_FALLBACK_DESCENDING = true  (on error, also try next tier down)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config.cortex_settings import CortexSettings

from providers.cortex.scorer import (
    TIER_LOCAL,
    TIER_NATIVE,
    TIER_ORDER,
    TIER_REMOTE,
    TIER_SMART,
)


@dataclass
class TierConfig:
    """Runtime tier configuration parsed from settings."""

    # Ordered provider/model strings per tier
    models: dict[str, list[str]] = field(default_factory=dict)
    # Minimum score to route to each tier
    thresholds: dict[str, int] = field(default_factory=dict)
    # Whether to try a higher tier on failure
    fallback_ascending: bool = True
    # Whether to try a lower tier on failure after ascending exhausted
    fallback_descending: bool = True

    def tiers_for_score(self, score: int) -> list[str]:
        """Return ordered list of tiers to try for a given score.

        Starts at the scored tier, then ascends (smarter), then descends (cheaper).
        Only includes tiers that have at least one model configured.
        """
        from providers.cortex.scorer import score_to_tier

        primary = score_to_tier(score, self.thresholds)
        primary_idx = TIER_ORDER.index(primary) if primary in TIER_ORDER else 0

        candidates: list[str] = []

        # Primary tier first
        if self._has_models(primary):
            candidates.append(primary)

        # Ascending fallback (smarter tiers)
        if self.fallback_ascending:
            candidates.extend(
                tier for tier in TIER_ORDER[primary_idx + 1 :] if self._has_models(tier)
            )

        # Descending fallback (cheaper tiers)
        if self.fallback_descending:
            candidates.extend(
                tier
                for tier in reversed(TIER_ORDER[:primary_idx])
                if self._has_models(tier)
            )

        return candidates

    def models_for_tier(self, tier: str) -> list[str]:
        """Return provider/model strings for a tier."""
        return self.models.get(tier, [])

    def _has_models(self, tier: str) -> bool:
        return bool(self.models.get(tier))

    @classmethod
    def from_cortex_settings(cls, cs: CortexSettings) -> TierConfig:
        """Build TierConfig from CortexSettings."""
        models: dict[str, list[str]] = {}
        for tier, raw in [
            (TIER_LOCAL, cs.cortex_local_models),
            (TIER_REMOTE, cs.cortex_remote_models),
            (TIER_SMART, cs.cortex_smart_models),
            (TIER_NATIVE, cs.cortex_native_models),
        ]:
            parsed = [m.strip() for m in raw.split(",") if m.strip()]
            if parsed:
                models[tier] = parsed

        thresholds = {
            TIER_LOCAL: cs.cortex_threshold_local,
            TIER_REMOTE: cs.cortex_threshold_remote,
            TIER_SMART: cs.cortex_threshold_smart,
            TIER_NATIVE: cs.cortex_threshold_native,
        }

        return cls(
            models=models,
            thresholds=thresholds,
            fallback_ascending=cs.cortex_fallback_ascending,
            fallback_descending=cs.cortex_fallback_descending,
        )

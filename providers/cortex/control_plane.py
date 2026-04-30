"""Cortex Control Plane — live runtime configuration.

Holds mutable routing state that can be changed via the dashboard API
without restarting the server. The CortexProvider reads from this on
every request.

State managed here:
- Score thresholds per tier (override env defaults)
- Manually opened/closed circuits per provider/model
- Client → tier/provider pin rules
- Tier model lists (add/remove models at runtime)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from loguru import logger

from providers.cortex.scorer import (
    TIER_LOCAL,
    TIER_NATIVE,
    TIER_ORDER,
    TIER_REMOTE,
    TIER_SMART,
)

# ── Singleton ─────────────────────────────────────────────────────────────────
_instance: CortexControlPlane | None = None
_lock = asyncio.Lock()


def get_control_plane() -> CortexControlPlane:
    global _instance
    if _instance is None:
        _instance = CortexControlPlane()
    return _instance


# ── Client pin rule ────────────────────────────────────────────────────────────
@dataclass
class ClientPinRule:
    """Route a specific client directly to a tier or provider/model."""

    client: str  # e.g. "claude-code", "hermes", "open-webui"
    target: str  # tier name ("smart") or "provider/model" string


# ── Control plane ──────────────────────────────────────────────────────────────
class CortexControlPlane:
    """Live-editable routing configuration."""

    def __init__(self) -> None:
        # Score thresholds — None means use TierConfig defaults from env
        self._thresholds: dict[str, int | None] = {
            TIER_LOCAL: None,
            TIER_REMOTE: None,
            TIER_SMART: None,
            TIER_NATIVE: None,
        }
        # Manually forced circuit states: key → True (forced open) | False (forced closed)
        # True = disabled (skip), False = force-enabled (ignore auto-trip)
        self._manual_circuits: dict[str, bool] = {}
        # Client pin rules: client_name → ClientPinRule
        self._client_pins: dict[str, ClientPinRule] = {}
        # Runtime tier model overrides: tier → list of provider/model strings | None (use env)
        self._tier_model_overrides: dict[str, list[str] | None] = {}
        # Fallback flags
        self._fallback_ascending: bool | None = None
        self._fallback_descending: bool | None = None

    # ── Thresholds ─────────────────────────────────────────────────────────────

    def set_threshold(self, tier: str, value: int | None) -> None:
        """Set score threshold for a tier. None = use env default."""
        if tier not in TIER_ORDER:
            raise ValueError(f"Unknown tier: {tier!r}")
        self._thresholds[tier] = value
        logger.info("CORTEX_CP: threshold {} = {}", tier, value)

    def get_threshold(self, tier: str, default: int) -> int:
        """Return effective threshold for a tier."""
        override = self._thresholds.get(tier)
        return override if override is not None else default

    def get_all_thresholds(self, defaults: dict[str, int]) -> dict[str, int]:
        """Return effective thresholds merging overrides with defaults."""
        return {
            tier: self.get_threshold(tier, defaults.get(tier, 0)) for tier in TIER_ORDER
        }

    # ── Manual circuit control ─────────────────────────────────────────────────

    def force_circuit_open(self, key: str) -> None:
        """Manually disable a provider/model (force circuit open)."""
        self._manual_circuits[key] = True
        logger.info("CORTEX_CP: circuit FORCED OPEN for {}", key)

    def force_circuit_closed(self, key: str) -> None:
        """Manually re-enable a provider/model (force circuit closed)."""
        self._manual_circuits[key] = False
        logger.info("CORTEX_CP: circuit FORCED CLOSED for {}", key)

    def clear_circuit_override(self, key: str) -> None:
        """Remove manual override — let auto circuit breaker decide."""
        self._manual_circuits.pop(key, None)
        logger.info("CORTEX_CP: circuit override cleared for {}", key)

    def is_manually_disabled(self, key: str) -> bool:
        """Return True if this provider/model is manually forced open."""
        return self._manual_circuits.get(key) is True

    def is_manually_enabled(self, key: str) -> bool:
        """Return True if this provider/model is manually forced closed (bypass auto)."""
        return self._manual_circuits.get(key) is False

    def get_manual_circuits(self) -> dict[str, bool]:
        return dict(self._manual_circuits)

    # ── Client pin rules ───────────────────────────────────────────────────────

    def set_client_pin(self, client: str, target: str) -> None:
        """Pin a client to a tier or provider/model."""
        self._client_pins[client] = ClientPinRule(client=client, target=target)
        logger.info("CORTEX_CP: client {} pinned to {}", client, target)

    def clear_client_pin(self, client: str) -> None:
        """Remove client pin — use normal routing."""
        self._client_pins.pop(client, None)
        logger.info("CORTEX_CP: client {} pin cleared", client)

    def get_client_pin(self, client: str) -> str | None:
        """Return pin target for client, or None if not pinned."""
        rule = self._client_pins.get(client)
        return rule.target if rule else None

    def get_all_client_pins(self) -> dict[str, str]:
        return {k: v.target for k, v in self._client_pins.items()}

    # ── Tier model overrides ───────────────────────────────────────────────────

    def set_tier_models(self, tier: str, models: list[str] | None) -> None:
        """Override models for a tier at runtime. None = use env default."""
        if tier not in TIER_ORDER:
            raise ValueError(f"Unknown tier: {tier!r}")
        self._tier_model_overrides[tier] = models
        logger.info("CORTEX_CP: tier {} models = {}", tier, models)

    def get_tier_models(self, tier: str, default: list[str]) -> list[str]:
        override = self._tier_model_overrides.get(tier)
        return override if override is not None else default

    # ── Fallback flags ─────────────────────────────────────────────────────────

    def set_fallback(self, ascending: bool | None, descending: bool | None) -> None:
        if ascending is not None:
            self._fallback_ascending = ascending
        if descending is not None:
            self._fallback_descending = descending

    def get_fallback_ascending(self, default: bool) -> bool:
        return (
            self._fallback_ascending
            if self._fallback_ascending is not None
            else default
        )

    def get_fallback_descending(self, default: bool) -> bool:
        return (
            self._fallback_descending
            if self._fallback_descending is not None
            else default
        )

    # ── Snapshot for dashboard ─────────────────────────────────────────────────

    def snapshot(self, tier_config_defaults: Any) -> dict[str, Any]:
        """Return full control plane state for the dashboard."""
        defaults = tier_config_defaults.thresholds if tier_config_defaults else {}
        tier_models: dict[str, list[str]] = {}
        for tier in TIER_ORDER:
            default_models = (
                tier_config_defaults.models.get(tier, [])
                if tier_config_defaults
                else []
            )
            tier_models[tier] = self.get_tier_models(tier, default_models)

        return {
            "thresholds": self.get_all_thresholds(defaults),
            "manual_circuits": self.get_manual_circuits(),
            "client_pins": self.get_all_client_pins(),
            "tier_models": tier_models,
            "fallback_ascending": self.get_fallback_ascending(
                tier_config_defaults.fallback_ascending
                if tier_config_defaults
                else True
            ),
            "fallback_descending": self.get_fallback_descending(
                tier_config_defaults.fallback_descending
                if tier_config_defaults
                else True
            ),
        }

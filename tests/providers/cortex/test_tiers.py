"""Tests for Cortex TierConfig."""

from __future__ import annotations

from unittest.mock import MagicMock

from providers.cortex.scorer import TIER_LOCAL, TIER_NATIVE, TIER_REMOTE, TIER_SMART
from providers.cortex.tiers import TierConfig


def _make_tier_config(
    local: list[str] | None = None,
    remote: list[str] | None = None,
    smart: list[str] | None = None,
    native: list[str] | None = None,
    thresholds: dict | None = None,
    fallback_ascending: bool = True,
    fallback_descending: bool = True,
) -> TierConfig:
    models = {}
    if local:
        models[TIER_LOCAL] = local
    if remote:
        models[TIER_REMOTE] = remote
    if smart:
        models[TIER_SMART] = smart
    if native:
        models[TIER_NATIVE] = native
    return TierConfig(
        models=models,
        thresholds=thresholds
        or {TIER_LOCAL: 0, TIER_REMOTE: 25, TIER_SMART: 55, TIER_NATIVE: 85},
        fallback_ascending=fallback_ascending,
        fallback_descending=fallback_descending,
    )


class TestTiersForScore:
    def test_low_score_starts_at_local(self) -> None:
        cfg = _make_tier_config(
            local=["lmstudio/gemma"], smart=["nvidia_nim/deepseek-ai/deepseek-v4-pro"]
        )
        tiers = cfg.tiers_for_score(10)
        assert tiers[0] == TIER_LOCAL

    def test_high_score_starts_at_smart(self) -> None:
        cfg = _make_tier_config(
            local=["lmstudio/gemma"], smart=["nvidia_nim/deepseek-ai/deepseek-v4-pro"]
        )
        tiers = cfg.tiers_for_score(60)
        assert tiers[0] == TIER_SMART

    def test_ascending_fallback_included(self) -> None:
        cfg = _make_tier_config(
            local=["lmstudio/gemma"],
            smart=["nvidia_nim/deepseek-ai/deepseek-v4-pro"],
            fallback_ascending=True,
            fallback_descending=False,
        )
        tiers = cfg.tiers_for_score(10)
        assert TIER_SMART in tiers
        assert tiers.index(TIER_LOCAL) < tiers.index(TIER_SMART)

    def test_descending_fallback_included(self) -> None:
        cfg = _make_tier_config(
            local=["lmstudio/gemma"],
            smart=["nvidia_nim/deepseek-ai/deepseek-v4-pro"],
            fallback_ascending=False,
            fallback_descending=True,
        )
        tiers = cfg.tiers_for_score(60)
        assert TIER_LOCAL in tiers
        assert tiers.index(TIER_SMART) < tiers.index(TIER_LOCAL)

    def test_no_fallback(self) -> None:
        cfg = _make_tier_config(
            local=["lmstudio/gemma"],
            smart=["nvidia_nim/deepseek-ai/deepseek-v4-pro"],
            fallback_ascending=False,
            fallback_descending=False,
        )
        tiers = cfg.tiers_for_score(10)
        assert tiers == [TIER_LOCAL]

    def test_unconfigured_tier_skipped(self) -> None:
        # Only local and native configured — remote and smart skipped
        cfg = _make_tier_config(
            local=["lmstudio/gemma"],
            native=["open_router/anthropic/claude-opus-4"],
        )
        tiers = cfg.tiers_for_score(10)
        assert TIER_REMOTE not in tiers
        assert TIER_SMART not in tiers
        assert TIER_LOCAL in tiers
        assert TIER_NATIVE in tiers


class TestFromCortexSettings:
    def test_parses_models_from_settings(self) -> None:
        cs = MagicMock()
        cs.cortex_local_models = "lmstudio/gemma,ollama/llama3"
        cs.cortex_remote_models = ""
        cs.cortex_smart_models = "nvidia_nim/deepseek-ai/deepseek-v4-pro"
        cs.cortex_native_models = ""
        cs.cortex_threshold_local = 0
        cs.cortex_threshold_remote = 25
        cs.cortex_threshold_smart = 55
        cs.cortex_threshold_native = 85
        cs.cortex_fallback_ascending = True
        cs.cortex_fallback_descending = True

        cfg = TierConfig.from_cortex_settings(cs)
        assert cfg.models[TIER_LOCAL] == ["lmstudio/gemma", "ollama/llama3"]
        assert cfg.models[TIER_SMART] == ["nvidia_nim/deepseek-ai/deepseek-v4-pro"]
        assert TIER_REMOTE not in cfg.models
        assert TIER_NATIVE not in cfg.models

    def test_empty_models_not_added(self) -> None:
        cs = MagicMock()
        cs.cortex_local_models = ""
        cs.cortex_remote_models = ""
        cs.cortex_smart_models = ""
        cs.cortex_native_models = ""
        cs.cortex_threshold_local = 0
        cs.cortex_threshold_remote = 25
        cs.cortex_threshold_smart = 55
        cs.cortex_threshold_native = 85
        cs.cortex_fallback_ascending = True
        cs.cortex_fallback_descending = True

        cfg = TierConfig.from_cortex_settings(cs)
        assert cfg.models == {}

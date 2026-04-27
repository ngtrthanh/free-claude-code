"""Tests for Cortex complexity scorer."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from providers.cortex.scorer import (
    TIER_LOCAL,
    TIER_NATIVE,
    TIER_REMOTE,
    TIER_SMART,
    score_request,
    score_to_tier,
)

_DEFAULT_THRESHOLDS = {
    TIER_LOCAL: 0,
    TIER_REMOTE: 25,
    TIER_SMART: 55,
    TIER_NATIVE: 85,
}


def _make_request(
    model: str = "claude-haiku-4-20251001",
    tools: list | None = None,
    messages: list | None = None,
    thinking: dict | None = None,
) -> MagicMock:
    req = MagicMock()
    req.model = model
    req.tools = tools or []
    req.messages = messages or [{"role": "user", "content": "hi"}]
    req.thinking = thinking
    return req


class TestScoreRequest:
    def test_minimal_haiku_request_scores_low(self) -> None:
        req = _make_request()
        assert score_request(req, input_tokens=10) < 25

    def test_opus_model_adds_score(self) -> None:
        haiku = _make_request(model="claude-haiku-4-20251001")
        opus = _make_request(model="claude-opus-4-20250514")
        assert score_request(opus) > score_request(haiku)

    def test_thinking_enabled_adds_score(self) -> None:
        no_think = _make_request()
        with_think = _make_request(thinking={"type": "enabled"})
        assert score_request(with_think) > score_request(no_think)

    def test_many_tools_adds_score(self) -> None:
        no_tools = _make_request(tools=[])
        many_tools = _make_request(tools=[{"name": f"tool_{i}"} for i in range(15)])
        assert score_request(many_tools) > score_request(no_tools)

    def test_large_token_count_adds_score(self) -> None:
        small = score_request(_make_request(), input_tokens=100)
        large = score_request(_make_request(), input_tokens=50_000)
        assert large > small

    def test_long_conversation_adds_score(self) -> None:
        short = _make_request(messages=[{"role": "user", "content": "hi"}])
        long = _make_request(
            messages=[{"role": "user", "content": "hi"}] * 20
        )
        assert score_request(long) > score_request(short)

    def test_score_capped_at_100(self) -> None:
        req = _make_request(
            model="claude-opus-4-20250514",
            tools=[{"name": f"t{i}"} for i in range(20)],
            messages=[{"role": "user", "content": "x"}] * 30,
            thinking={"type": "enabled"},
        )
        assert score_request(req, input_tokens=100_000) == 100

    def test_thinking_disabled_no_bonus(self) -> None:
        disabled = _make_request(thinking={"type": "disabled"})
        no_thinking = _make_request()
        assert score_request(disabled) == score_request(no_thinking)


class TestScoreToTier:
    def test_score_0_maps_to_local(self) -> None:
        assert score_to_tier(0, _DEFAULT_THRESHOLDS) == TIER_LOCAL

    def test_score_24_maps_to_local(self) -> None:
        assert score_to_tier(24, _DEFAULT_THRESHOLDS) == TIER_LOCAL

    def test_score_25_maps_to_remote(self) -> None:
        assert score_to_tier(25, _DEFAULT_THRESHOLDS) == TIER_REMOTE

    def test_score_55_maps_to_smart(self) -> None:
        assert score_to_tier(55, _DEFAULT_THRESHOLDS) == TIER_SMART

    def test_score_85_maps_to_native(self) -> None:
        assert score_to_tier(85, _DEFAULT_THRESHOLDS) == TIER_NATIVE

    def test_score_100_maps_to_native(self) -> None:
        assert score_to_tier(100, _DEFAULT_THRESHOLDS) == TIER_NATIVE

    def test_custom_thresholds(self) -> None:
        thresholds = {TIER_LOCAL: 0, TIER_SMART: 10}
        assert score_to_tier(5, thresholds) == TIER_LOCAL
        assert score_to_tier(10, thresholds) == TIER_SMART
        assert score_to_tier(99, thresholds) == TIER_SMART

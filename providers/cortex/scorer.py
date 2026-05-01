"""Request complexity scorer for Cortex routing.

Scores a request 0-100 and maps it to a tier name.
Higher score = more complex = needs a smarter/heavier provider.

Scoring factors
---------------
- Token count          : proxy for context size / conversation depth
- Tool count           : tool-heavy requests need capable models
- Thinking requested   : explicit reasoning → heavy tier
- Model tier hint      : opus > sonnet > haiku from the original Claude model name
- Message count        : long conversations are harder
- System prompt length : large system prompts add complexity
"""

from __future__ import annotations

from typing import Any

# ── Tier names (ordered cheapest → most capable) ──────────────────────────────
TIER_LOCAL = "local"  # free, on-device (oMLX, Ollama, llama.cpp)
TIER_REMOTE = "remote"  # cheap cloud (OpenRouter free, DeepSeek)
TIER_SMART = "smart"  # capable cloud (NVIDIA NIM, OpenRouter paid)
TIER_NATIVE = "native"  # native Anthropic (most capable, costs real money)

TIER_ORDER = (TIER_LOCAL, TIER_REMOTE, TIER_SMART, TIER_NATIVE)


def _model_tier_score(model_name: str) -> int:
    """Return a base score from the Claude model tier hint."""
    # Check original model name from request context (before routing)
    try:
        from core.request_context import original_model

        orig = original_model.get()
        if orig:
            model_name = orig
    except Exception:
        pass

    name = model_name.lower()
    if "opus" in name:
        return 40
    if "sonnet" in name:
        return 20
    # haiku or unknown
    return 0


def _thinking_score(request: Any) -> int:
    """Return extra score when thinking/reasoning is explicitly requested."""
    thinking = getattr(request, "thinking", None)
    if thinking is None:
        return 0
    thinking_type = (
        thinking.get("type")
        if isinstance(thinking, dict)
        else getattr(thinking, "type", None)
    )
    if thinking_type == "enabled":
        return 30
    enabled = (
        thinking.get("enabled")
        if isinstance(thinking, dict)
        else getattr(thinking, "enabled", None)
    )
    if enabled:
        return 30
    return 0


def _tool_score(request: Any) -> int:
    """Return extra score based on number of tools defined."""
    tools = getattr(request, "tools", None) or []
    count = len(tools)
    if count == 0:
        return 0
    if count <= 3:
        return 10
    if count <= 10:
        return 20
    return 30


def _token_score(input_tokens: int) -> int:
    """Return extra score based on estimated input token count."""
    if input_tokens < 500:
        return 0
    if input_tokens < 2_000:
        return 5
    if input_tokens < 8_000:
        return 15
    if input_tokens < 32_000:
        return 25
    return 35


def _message_depth_score(request: Any) -> int:
    """Return extra score for long conversation depth."""
    messages = getattr(request, "messages", None) or []
    count = len(messages)
    if count <= 2:
        return 0
    if count <= 6:
        return 5
    if count <= 15:
        return 10
    return 15


def score_request(request: Any, input_tokens: int = 0) -> int:
    """Return a complexity score 0-100 for the request."""
    score = 0
    score += _model_tier_score(getattr(request, "model", ""))
    score += _thinking_score(request)
    score += _tool_score(request)
    score += _token_score(input_tokens)
    score += _message_depth_score(request)
    return min(score, 100)


def score_to_tier(score: int, thresholds: dict[str, int]) -> str:
    """Map a score to a tier name using configured thresholds.

    ``thresholds`` maps tier name → minimum score to use that tier.
    Example: {"local": 0, "remote": 20, "smart": 50, "native": 80}
    """
    # Walk tiers from most capable down; pick the highest tier whose threshold ≤ score
    best = TIER_LOCAL
    for tier in TIER_ORDER:
        min_score = thresholds.get(tier, 999)
        if score >= min_score:
            best = tier
    return best

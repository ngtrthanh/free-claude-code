"""Per-request context variables (client identity, request ID, etc.)."""

from __future__ import annotations

from contextvars import ContextVar

# Set at the start of each request handler; read by the provider layer
current_client: ContextVar[str] = ContextVar("current_client", default="unknown")

# Original Claude model name before routing (e.g. "claude-sonnet-4-20250514")
# Used by Cortex scorer to determine model tier even when model is "cortex-auto"
original_model: ContextVar[str] = ContextVar("original_model", default="")

"""Per-request context variables (client identity, request ID, etc.)."""

from __future__ import annotations

from contextvars import ContextVar

# Set at the start of each request handler; read by the provider layer
current_client: ContextVar[str] = ContextVar("current_client", default="unknown")

"""In-process metrics store for Cortex dashboard.

Thread-safe, async-friendly. Stores:
- Active connections (request_id → metadata)
- Routing history (last N decisions)
- Token throughput per provider
- Aggregate counters
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ActiveRequest:
    """Metadata for a currently streaming request."""

    request_id: str
    model: str
    provider_id: str
    provider_model: str
    tier: str
    score: int
    input_tokens: int
    started_at: float = field(default_factory=time.monotonic)
    output_tokens: int = 0
    tokens_per_second: float = 0.0
    last_token_at: float = field(default_factory=time.monotonic)

    def elapsed_s(self) -> float:
        return time.monotonic() - self.started_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "model": self.model,
            "provider_id": self.provider_id,
            "provider_model": self.provider_model,
            "tier": self.tier,
            "score": self.score,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "tokens_per_second": round(self.tokens_per_second, 1),
            "elapsed_s": round(self.elapsed_s(), 1),
        }


@dataclass
class RoutingEvent:
    """A completed routing decision."""

    request_id: str
    model: str
    provider_id: str
    provider_model: str
    tier: str
    score: int
    input_tokens: int
    output_tokens: int
    duration_s: float
    tokens_per_second: float
    success: bool
    fallback_count: int
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "model": self.model,
            "provider_id": self.provider_id,
            "provider_model": self.provider_model,
            "tier": self.tier,
            "score": self.score,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "duration_s": round(self.duration_s, 2),
            "tokens_per_second": round(self.tokens_per_second, 1),
            "success": self.success,
            "fallback_count": self.fallback_count,
            "timestamp": self.timestamp,
        }


class CortexMetrics:
    """Central metrics store. One instance per process."""

    _instance: CortexMetrics | None = None

    def __init__(self, history_size: int = 50) -> None:
        self._lock = asyncio.Lock()
        self._active: dict[str, ActiveRequest] = {}
        self._history: deque[RoutingEvent] = deque(maxlen=history_size)
        self._total_requests: int = 0
        self._total_tokens_in: int = 0
        self._total_tokens_out: int = 0
        self._total_fallbacks: int = 0
        self._provider_counts: dict[str, int] = {}
        self._tier_counts: dict[str, int] = {}
        self._subscribers: list[asyncio.Queue[dict[str, Any]]] = []

    @classmethod
    def get(cls) -> CortexMetrics:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    # ── Active request tracking ────────────────────────────────────────────────

    async def request_started(
        self,
        request_id: str,
        model: str,
        provider_id: str,
        provider_model: str,
        tier: str,
        score: int,
        input_tokens: int,
    ) -> None:
        async with self._lock:
            self._active[request_id] = ActiveRequest(
                request_id=request_id,
                model=model,
                provider_id=provider_id,
                provider_model=provider_model,
                tier=tier,
                score=score,
                input_tokens=input_tokens,
            )
            self._total_requests += 1
            self._total_tokens_in += input_tokens
            self._provider_counts[provider_id] = (
                self._provider_counts.get(provider_id, 0) + 1
            )
            self._tier_counts[tier] = self._tier_counts.get(tier, 0) + 1
        await self._broadcast()

    async def token_emitted(self, request_id: str) -> None:
        """Record a single output token for throughput calculation."""
        async with self._lock:
            req = self._active.get(request_id)
            if req is None:
                return
            now = time.monotonic()
            req.output_tokens += 1
            self._total_tokens_out += 1
            elapsed = now - req.started_at
            if elapsed > 0:
                req.tokens_per_second = req.output_tokens / elapsed
            req.last_token_at = now
        # Broadcast every 5 tokens to avoid flooding
        if (
            self._active.get(request_id)
            and self._active[request_id].output_tokens % 5 == 0
        ):
            await self._broadcast()

    async def request_finished(
        self,
        request_id: str,
        success: bool,
        fallback_count: int = 0,
    ) -> None:
        async with self._lock:
            req = self._active.pop(request_id, None)
            if req is None:
                return
            duration = time.monotonic() - req.started_at
            tps = req.output_tokens / duration if duration > 0 else 0.0
            if fallback_count > 0:
                self._total_fallbacks += fallback_count
            event = RoutingEvent(
                request_id=request_id,
                model=req.model,
                provider_id=req.provider_id,
                provider_model=req.provider_model,
                tier=req.tier,
                score=req.score,
                input_tokens=req.input_tokens,
                output_tokens=req.output_tokens,
                duration_s=duration,
                tokens_per_second=tps,
                success=success,
                fallback_count=fallback_count,
            )
            self._history.append(event)
        await self._broadcast()

    # ── Snapshot ───────────────────────────────────────────────────────────────

    async def snapshot(self) -> dict[str, Any]:
        from providers.registry import get_cortex_brain

        async with self._lock:
            active = [r.to_dict() for r in self._active.values()]
            history = [e.to_dict() for e in reversed(self._history)]
            total_req = self._total_requests
            total_in = self._total_tokens_in
            total_out = self._total_tokens_out
            total_fb = self._total_fallbacks
            provider_counts = dict(self._provider_counts)
            tier_counts = dict(self._tier_counts)

        # Current aggregate tps across all active streams
        now = time.monotonic()
        current_tps = sum(
            r["tokens_per_second"]
            for r in active
            if now - (r.get("elapsed_s", 0) + time.monotonic() - now) < 5
        )

        return {
            "brain": get_cortex_brain() or "auto",
            "active_connections": len(active),
            "active": active,
            "history": history,
            "totals": {
                "requests": total_req,
                "tokens_in": total_in,
                "tokens_out": total_out,
                "fallbacks": total_fb,
            },
            "current_tps": round(current_tps, 1),
            "provider_counts": provider_counts,
            "tier_counts": tier_counts,
            "timestamp": time.time(),
        }

    # ── SSE pub/sub ────────────────────────────────────────────────────────────

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=20)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    async def _broadcast(self) -> None:
        snap = await self.snapshot()
        dead = []
        for q in self._subscribers:
            try:
                q.put_nowait(snap)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self.unsubscribe(q)

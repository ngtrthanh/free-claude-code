"""Cortex dashboard — served at GET /dashboard.

HTML lives in api/dashboard.html (edit that file directly).
This module handles the FastAPI routes and SSE stream only.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, StreamingResponse

dashboard_router = APIRouter()

# Path to the dashboard HTML file — resolved relative to this module
_DASHBOARD_HTML_PATH = Path(__file__).parent / "dashboard.html"


def _load_dashboard_html() -> str:
    """Read dashboard HTML from disk. Always fresh — no caching."""
    return _DASHBOARD_HTML_PATH.read_text(encoding="utf-8")


@dashboard_router.get(
    "/dashboard", response_class=HTMLResponse, include_in_schema=False
)
async def dashboard() -> HTMLResponse:
    """Serve the Cortex real-time dashboard."""
    return HTMLResponse(_load_dashboard_html())


@dashboard_router.get("/dashboard/stream", include_in_schema=False)
async def dashboard_stream() -> StreamingResponse:
    """SSE stream of live Cortex metrics."""
    from core.cortex_metrics import CortexMetrics

    metrics = CortexMetrics.get()

    async def event_stream() -> AsyncIterator[str]:
        # Send initial snapshot immediately
        snap = await metrics.snapshot()
        yield f"data: {json.dumps(snap)}\n\n"

        q = metrics.subscribe()
        try:
            while True:
                try:
                    data = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {json.dumps(data)}\n\n"
                except TimeoutError:
                    # Heartbeat to keep connection alive
                    snap = await metrics.snapshot()
                    yield f"data: {json.dumps(snap)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            metrics.unsubscribe(q)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

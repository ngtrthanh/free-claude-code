"""Cortex dashboard — served at GET /dashboard.

Single-page HTML with real-time SSE updates. No external dependencies.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, StreamingResponse

dashboard_router = APIRouter()

_DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Cortex Dashboard</title>
<style>
  :root {
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --text: #e6edf3; --muted: #8b949e; --accent: #58a6ff;
    --green: #3fb950; --yellow: #d29922; --red: #f85149;
    --purple: #bc8cff; --orange: #ffa657;
    --local: #3fb950; --remote: #58a6ff; --smart: #d29922; --native: #f85149; --direct: #bc8cff; --fallback: #8b949e;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: 'SF Mono', 'Fira Code', monospace; font-size: 13px; }
  header { background: var(--surface); border-bottom: 1px solid var(--border); padding: 12px 20px; display: flex; align-items: center; gap: 16px; }
  header h1 { font-size: 16px; font-weight: 600; color: var(--accent); }
  .badge { padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; }
  .badge-green { background: #1a3a1a; color: var(--green); border: 1px solid var(--green); }
  .badge-red { background: #3a1a1a; color: var(--red); border: 1px solid var(--red); }
  .status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--green); animation: pulse 2s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; padding: 16px 20px; }
  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 14px; }
  .card-label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .5px; margin-bottom: 6px; }
  .card-value { font-size: 28px; font-weight: 700; color: var(--text); }
  .card-sub { color: var(--muted); font-size: 11px; margin-top: 4px; }
  .brain-badge { display: inline-block; padding: 3px 10px; border-radius: 6px; font-size: 13px; font-weight: 700; }
  .brain-auto { background: #1a2a3a; color: var(--accent); }
  .brain-local { background: #1a3a1a; color: var(--local); }
  .brain-remote { background: #1a2a3a; color: var(--remote); }
  .brain-smart { background: #3a2a1a; color: var(--smart); }
  .brain-native { background: #3a1a1a; color: var(--native); }
  .brain-direct { background: #2a1a3a; color: var(--purple); }
  section { padding: 0 20px 16px; }
  section h2 { font-size: 12px; text-transform: uppercase; letter-spacing: .5px; color: var(--muted); margin-bottom: 10px; padding-top: 4px; }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; color: var(--muted); font-size: 11px; font-weight: 500; padding: 6px 8px; border-bottom: 1px solid var(--border); }
  td { padding: 7px 8px; border-bottom: 1px solid #21262d; vertical-align: middle; }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: #1c2128; }
  .tier-pill { display: inline-block; padding: 1px 7px; border-radius: 10px; font-size: 11px; font-weight: 600; }
  .tier-local { background: #1a3a1a; color: var(--local); }
  .tier-remote { background: #1a2a3a; color: var(--remote); }
  .tier-smart { background: #3a2a1a; color: var(--smart); }
  .tier-native { background: #3a1a1a; color: var(--native); }
  .tier-direct { background: #2a1a3a; color: var(--purple); }
  .tier-fallback { background: #2a2a2a; color: var(--muted); }
  .score-bar { display: flex; align-items: center; gap: 6px; }
  .score-track { flex: 1; height: 4px; background: #21262d; border-radius: 2px; overflow: hidden; max-width: 80px; }
  .score-fill { height: 100%; border-radius: 2px; transition: width .3s; }
  .tps-value { color: var(--green); font-weight: 600; }
  .empty { color: var(--muted); font-style: italic; padding: 16px 8px; }
  .bar-chart { display: flex; gap: 8px; align-items: flex-end; height: 60px; padding: 4px 0; }
  .bar-wrap { display: flex; flex-direction: column; align-items: center; gap: 3px; flex: 1; }
  .bar { width: 100%; border-radius: 3px 3px 0 0; transition: height .4s; min-height: 2px; }
  .bar-label { font-size: 10px; color: var(--muted); white-space: nowrap; }
  .bar-count { font-size: 10px; color: var(--text); }
  .success-dot { color: var(--green); }
  .fail-dot { color: var(--red); }
  .elapsed { color: var(--muted); }
  .provider-name { color: var(--accent); }
  .model-name { color: var(--muted); font-size: 11px; }
  .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; padding: 0 20px 16px; }
  @media (max-width: 700px) { .two-col { grid-template-columns: 1fr; } }
</style>
</head>
<body>

<header>
  <div class="status-dot" id="dot"></div>
  <h1>⚡ Cortex</h1>
  <span id="brain-badge" class="brain-badge brain-auto">auto</span>
  <span style="margin-left:auto;color:var(--muted);font-size:11px" id="last-update">—</span>
</header>

<div class="grid">
  <div class="card">
    <div class="card-label">Active Connections</div>
    <div class="card-value" id="active-count">0</div>
    <div class="card-sub" id="active-tps">0 tok/s</div>
  </div>
  <div class="card">
    <div class="card-label">Total Requests</div>
    <div class="card-value" id="total-req">0</div>
    <div class="card-sub" id="total-fallbacks">0 fallbacks</div>
  </div>
  <div class="card">
    <div class="card-label">Tokens In</div>
    <div class="card-value" id="tokens-in">0</div>
    <div class="card-sub">input tokens total</div>
  </div>
  <div class="card">
    <div class="card-label">Tokens Out</div>
    <div class="card-value" id="tokens-out">0</div>
    <div class="card-sub">output tokens total</div>
  </div>
</div>

<div class="two-col">
  <div class="card">
    <div class="card-label" style="margin-bottom:10px">Requests by Tier</div>
    <div class="bar-chart" id="tier-chart"></div>
  </div>
  <div class="card">
    <div class="card-label" style="margin-bottom:10px">Requests by Provider</div>
    <div class="bar-chart" id="provider-chart"></div>
  </div>
</div>

<section>
  <h2>Active Streams</h2>
  <table id="active-table">
    <thead><tr>
      <th>Request ID</th><th>Model</th><th>Tier</th><th>Score</th>
      <th>Provider</th><th>Tokens Out</th><th>Speed</th><th>Elapsed</th>
    </tr></thead>
    <tbody id="active-body"><tr><td colspan="8" class="empty">No active streams</td></tr></tbody>
  </table>
</section>

<section>
  <h2>Recent Routing History</h2>
  <table id="history-table">
    <thead><tr>
      <th>Request ID</th><th>Model</th><th>Tier</th><th>Score</th>
      <th>Provider</th><th>In</th><th>Out</th><th>Speed</th><th>Duration</th><th>Status</th>
    </tr></thead>
    <tbody id="history-body"><tr><td colspan="10" class="empty">No history yet</td></tr></tbody>
  </table>
</section>

<script>
const TIER_COLORS = {
  local: '#3fb950', remote: '#58a6ff', smart: '#d29922',
  native: '#f85149', direct: '#bc8cff', fallback: '#8b949e', auto: '#58a6ff'
};

function tierPill(tier) {
  return `<span class="tier-pill tier-${tier}">${tier}</span>`;
}

function scoreBar(score) {
  const pct = Math.min(score, 100);
  const color = pct < 25 ? '#3fb950' : pct < 55 ? '#58a6ff' : pct < 85 ? '#d29922' : '#f85149';
  return `<div class="score-bar">
    <span>${score}</span>
    <div class="score-track"><div class="score-fill" style="width:${pct}%;background:${color}"></div></div>
  </div>`;
}

function fmtNum(n) {
  if (n >= 1e6) return (n/1e6).toFixed(1)+'M';
  if (n >= 1e3) return (n/1e3).toFixed(1)+'K';
  return n;
}

function fmtTime(ts) {
  return new Date(ts * 1000).toLocaleTimeString();
}

function renderBarChart(el, data, colorMap) {
  if (!data || Object.keys(data).length === 0) { el.innerHTML = '<span style="color:var(--muted);font-size:11px">No data</span>'; return; }
  const max = Math.max(...Object.values(data), 1);
  el.innerHTML = Object.entries(data).map(([k, v]) => {
    const h = Math.max(4, Math.round((v / max) * 52));
    const color = colorMap[k] || '#8b949e';
    return `<div class="bar-wrap">
      <div class="bar-count">${v}</div>
      <div class="bar" style="height:${h}px;background:${color}"></div>
      <div class="bar-label">${k}</div>
    </div>`;
  }).join('');
}

function update(data) {
  // Header
  const brain = data.brain || 'auto';
  const bb = document.getElementById('brain-badge');
  bb.textContent = brain;
  bb.className = `brain-badge brain-${brain.split('/')[0]}`;
  document.getElementById('last-update').textContent = 'Updated ' + new Date().toLocaleTimeString();

  // Stats
  document.getElementById('active-count').textContent = data.active_connections;
  document.getElementById('active-tps').textContent = data.current_tps + ' tok/s';
  document.getElementById('total-req').textContent = fmtNum(data.totals.requests);
  document.getElementById('total-fallbacks').textContent = data.totals.fallbacks + ' fallbacks';
  document.getElementById('tokens-in').textContent = fmtNum(data.totals.tokens_in);
  document.getElementById('tokens-out').textContent = fmtNum(data.totals.tokens_out);

  // Charts
  renderBarChart(document.getElementById('tier-chart'), data.tier_counts, TIER_COLORS);
  renderBarChart(document.getElementById('provider-chart'), data.provider_counts, {
    nvidia_nim: '#76b900', open_router: '#6e40c9', deepseek: '#1e90ff',
    lmstudio: '#ff6b35', ollama: '#00b4d8', llamacpp: '#e63946', cortex: '#58a6ff'
  });

  // Active streams
  const ab = document.getElementById('active-body');
  if (!data.active || data.active.length === 0) {
    ab.innerHTML = '<tr><td colspan="8" class="empty">No active streams</td></tr>';
  } else {
    ab.innerHTML = data.active.map(r => `<tr>
      <td style="font-size:11px;color:var(--muted)">${r.request_id.slice(-8)}</td>
      <td>${r.model}</td>
      <td>${tierPill(r.tier)}</td>
      <td>${scoreBar(r.score)}</td>
      <td><span class="provider-name">${r.provider_id}</span><br><span class="model-name">${r.provider_model}</span></td>
      <td>${r.output_tokens}</td>
      <td class="tps-value">${r.tokens_per_second} t/s</td>
      <td class="elapsed">${r.elapsed_s}s</td>
    </tr>`).join('');
  }

  // History
  const hb = document.getElementById('history-body');
  if (!data.history || data.history.length === 0) {
    hb.innerHTML = '<tr><td colspan="10" class="empty">No history yet</td></tr>';
  } else {
    hb.innerHTML = data.history.slice(0, 20).map(r => `<tr>
      <td style="font-size:11px;color:var(--muted)">${r.request_id.slice(-8)}</td>
      <td>${r.model}</td>
      <td>${tierPill(r.tier)}</td>
      <td>${scoreBar(r.score)}</td>
      <td><span class="provider-name">${r.provider_id}</span><br><span class="model-name">${r.provider_model}</span></td>
      <td>${fmtNum(r.input_tokens)}</td>
      <td>${fmtNum(r.output_tokens)}</td>
      <td class="tps-value">${r.tokens_per_second} t/s</td>
      <td>${r.duration_s}s</td>
      <td>${r.success ? '<span class="success-dot">✓</span>' : '<span class="fail-dot">✗</span>'} ${r.fallback_count > 0 ? `<span style="color:var(--yellow);font-size:10px">${r.fallback_count}fb</span>` : ''}</td>
    </tr>`).join('');
  }
}

// SSE connection
function connect() {
  const dot = document.getElementById('dot');
  const es = new EventSource('/dashboard/stream');

  es.onopen = () => { dot.style.background = 'var(--green)'; };
  es.onmessage = (e) => { try { update(JSON.parse(e.data)); } catch(err) { console.error(err); } };
  es.onerror = () => {
    dot.style.background = 'var(--red)';
    es.close();
    setTimeout(connect, 3000);
  };
}

connect();
</script>
</body>
</html>"""


@dashboard_router.get(
    "/dashboard", response_class=HTMLResponse, include_in_schema=False
)
async def dashboard() -> HTMLResponse:
    """Serve the Cortex real-time dashboard."""
    return HTMLResponse(_DASHBOARD_HTML)


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

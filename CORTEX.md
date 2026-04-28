# Cortex — Smart Routing Provider

Cortex is a meta-provider built into free-claude-code that automatically routes each request to the best available backend based on task complexity. Instead of hardcoding a single provider, Cortex scores every request and dispatches it to the right tier — local, remote, smart, or native — with automatic fallback on failure.

## How It Works

```
Claude Code / Hermes / any client
        │
        ▼
  free-claude-code (Cortex enabled)
        │
        ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │  Complexity Scorer (0-100)                                      │
  │  • Model tier hint  (haiku=+0, sonnet=+20, opus=+40)           │
  │  • Thinking enabled (explicit reasoning request = +30)          │
  │  • Tool count       (1-3=+10, 4-10=+20, 11+=+30)              │
  │  • Input tokens     (<500=+0, 2k-8k=+15, 32k+=+35)            │
  │  • Message depth    (3-6=+5, 7-15=+10, 16+=+15)               │
  └──────────────────────────────┬──────────────────────────────────┘
                                 │ score
                                 ▼
  ┌──────────────────────────────────────────────────────────────────┐
  │  Tier Router                                                     │
  │                                                                  │
  │  score  0-24  → LOCAL   LM Studio (192.168.11.13:1234)          │
  │                          model: google/gemma-4-e4b               │
  │                          transport: Anthropic /v1/messages (LAN) │
  │                                                                  │
  │  score 25-54  → REMOTE  OpenRouter free tier / DeepSeek         │
  │                          model: llama-3.1-8b-instruct:free       │
  │                          transport: Anthropic Messages (cloud)   │
  │                                                                  │
  │  score 55-84  → SMART   NVIDIA NIM / OpenRouter paid            │
  │                          model: deepseek-ai/deepseek-v4-pro      │
  │                          transport: OpenAI chat completions       │
  │                                                                  │
  │  score 85-100 → NATIVE  OpenRouter → Anthropic claude-opus-4    │
  │                          transport: Anthropic Messages (cloud)   │
  │                                                                  │
  │  On any error → fallback ascending (local→remote→smart→native)  │
  │               → then descending if all upper tiers fail          │
  └──────────────────────────────────────────────────────────────────┘
```

## Quick Start

Set `MODEL="cortex/auto"` in your `.env` and configure at least one tier:

```bash
MODEL="cortex/auto"

# LOCAL tier — LM Studio on LAN (score 0-24: quick/simple tasks)
LM_STUDIO_BASE_URL="http://192.168.11.13:1234/v1"
CORTEX_LOCAL_MODELS="lmstudio/google/gemma-4-e4b"

# SMART tier — NVIDIA NIM (score 55-84: complex reasoning, tools)
NVIDIA_NIM_API_KEY="your-key"
CORTEX_SMART_MODELS="nvidia_nim/deepseek-ai/deepseek-v4-pro"
```

That's it. Simple requests go to LM Studio on your LAN, complex ones go to NIM.

## Configuration Reference

### Tier Model Lists

Each tier takes a comma-separated list of `provider/model` strings. Cortex tries them left-to-right, falling back on error.

| Tier | Score Range | Variable | Current Config |
|---|---|---|---|
| **LOCAL** | 0–24 | `CORTEX_LOCAL_MODELS` | `lmstudio/google/gemma-4-e4b` |
| **REMOTE** | 25–54 | `CORTEX_REMOTE_MODELS` | `open_router/meta-llama/llama-3.1-8b-instruct:free` |
| **SMART** | 55–84 | `CORTEX_SMART_MODELS` | `nvidia_nim/deepseek-ai/deepseek-v4-pro` |
| **NATIVE** | 85–100 | `CORTEX_NATIVE_MODELS` | `open_router/anthropic/claude-opus-4` |

**LOCAL** = LM Studio running on your LAN at `192.168.11.13:1234`. Uses the native Anthropic `/v1/messages` endpoint that LM Studio exposes. Free, fast, private — no API quota consumed.

**REMOTE** = Cheap or free cloud models. OpenRouter free tier, DeepSeek API. Good for medium-complexity tasks that need more capability than local but don't justify NIM costs.

**SMART** = NVIDIA NIM with DeepSeek V4 Pro. Full reasoning, tools, thinking tokens. Used for complex coding tasks, multi-step reasoning, heavy tool use.

**NATIVE** = Native Anthropic claude-opus-4 via OpenRouter. Reserved for the hardest tasks (score 85+) — long context + thinking + many tools simultaneously.

Example with multiple fallbacks per tier:
```bash
CORTEX_LOCAL_MODELS="lmstudio/google/gemma-4-e4b,ollama/llama3.2"
CORTEX_REMOTE_MODELS="open_router/meta-llama/llama-3.1-8b-instruct:free,deepseek/deepseek-chat"
CORTEX_SMART_MODELS="nvidia_nim/deepseek-ai/deepseek-v4-pro,open_router/anthropic/claude-sonnet-4"
CORTEX_NATIVE_MODELS="open_router/anthropic/claude-opus-4"
```

### Score Thresholds

Control which score range maps to which tier.

| Variable | Default | Description |
|---|---|---|
| `CORTEX_THRESHOLD_LOCAL` | `0` | Min score for local tier |
| `CORTEX_THRESHOLD_REMOTE` | `25` | Min score for remote tier |
| `CORTEX_THRESHOLD_SMART` | `55` | Min score for smart tier |
| `CORTEX_THRESHOLD_NATIVE` | `85` | Min score for native tier |

### Fallback Behavior

| Variable | Default | Description |
|---|---|---|
| `CORTEX_FALLBACK_ASCENDING` | `true` | On error, try smarter tiers |
| `CORTEX_FALLBACK_DESCENDING` | `true` | On error, try cheaper tiers after ascending |

Set both to `false` to disable fallback (strict routing — fail if primary tier fails).

## Scoring Logic

Scores are additive, capped at 100:

| Signal | Score Added |
|---|---|
| Model is haiku | +0 |
| Model is sonnet | +20 |
| Model is opus | +40 |
| Thinking enabled | +30 |
| 1-3 tools | +10 |
| 4-10 tools | +20 |
| 11+ tools | +30 |
| < 500 input tokens | +0 |
| 500-2k tokens | +5 |
| 2k-8k tokens | +15 |
| 8k-32k tokens | +25 |
| 32k+ tokens | +35 |
| 3-6 messages | +5 |
| 7-15 messages | +10 |
| 16+ messages | +15 |

**Examples:**
- `say hi` with haiku → score **0** → local
- Medium task with sonnet + 5 tools → score **40** → remote
- Complex reasoning with opus + thinking + many tools → score **100** → native

## Switching Brains

### Via model name (Claude Code / Hermes)

Tell your agent to use a different model:

```
"use model cortex-local"    → force local tier
"use model cortex-remote"   → force remote tier
"use model cortex-smart"    → force smart tier
"use model cortex-native"   → force native tier
"use model cortex-auto"     → restore auto-routing
```

These are virtual model names — Cortex intercepts them and sets the tier override for the current process.

### Via API

```bash
# Force smart tier
curl -X POST http://localhost:8083/v1/cortex/brain \
  -H "x-api-key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"brain": "smart"}'

# Force a specific provider/model directly
curl -X POST http://localhost:8083/v1/cortex/brain \
  -H "x-api-key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"brain": "nvidia_nim/deepseek-ai/deepseek-v4-pro"}'

# Restore auto-routing
curl -X POST http://localhost:8083/v1/cortex/brain \
  -H "x-api-key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"brain": "auto"}'

# Check current brain
curl http://localhost:8083/v1/cortex/brain -H "x-api-key: your-key"
# → {"brain": "auto", "mode": "automatic"}
# → {"brain": "smart", "mode": "override"}
```

### Via ~/.bashrc (per-session)

```bash
# Quick aliases for switching brains
alias brain-local='curl -s -X POST http://localhost:8083/v1/cortex/brain -H "x-api-key: any" -H "Content-Type: application/json" -d "{\"brain\":\"local\"}" | python3 -m json.tool'
alias brain-smart='curl -s -X POST http://localhost:8083/v1/cortex/brain -H "x-api-key: any" -H "Content-Type: application/json" -d "{\"brain\":\"smart\"}" | python3 -m json.tool'
alias brain-auto='curl -s -X POST http://localhost:8083/v1/cortex/brain -H "x-api-key: any" -H "Content-Type: application/json" -d "{\"brain\":\"auto\"}" | python3 -m json.tool'
alias brain-status='curl -s http://localhost:8083/v1/cortex/brain -H "x-api-key: any" | python3 -m json.tool'
```

## Deployment

Cortex runs as a separate container on port 8083 at `/srv/lab/cortex`.

```bash
# Start
docker compose -f /srv/lab/cortex/docker-compose.yml up -d

# Check health
curl http://localhost:8083/health

# View logs (with routing decisions)
docker exec fcc-cortex cat /app/server.log | python3 -c "
import sys, json
for line in sys.stdin:
    try:
        d = json.loads(line)
        if 'CORTEX' in d.get('message','') or d.get('level') == 'ERROR':
            print(d['level'], d['message'])
    except: pass
"

# Update after code changes
docker build --security-opt apparmor:unconfined -t free-claude-code:cortex -f Dockerfile /srv/lab/free-claude-code
docker compose -f /srv/lab/cortex/docker-compose.yml down
docker compose -f /srv/lab/cortex/docker-compose.yml up -d
```

## Connecting Claude Code

```bash
# In ~/.bashrc — point Claude Code at Cortex
export ANTHROPIC_BASE_URL="http://localhost:8083"
export ANTHROPIC_AUTH_TOKEN="any"
```

Then `source ~/.bashrc` and Claude Code will use Cortex automatically.

## Connecting Hermes

In `~/.hermes/config.yaml`:
```yaml
model:
  default: claude-sonnet-4-20250514
  provider: anthropic
  base_url: http://localhost:8083
```

In `~/.hermes/.env`:
```bash
ANTHROPIC_API_KEY=any
```

## Per-Model Tier Routing

You can use Cortex for specific Claude model tiers while keeping others on fixed providers:

```bash
# Use Cortex for opus (complex tasks), fixed NIM for sonnet/haiku
MODEL_OPUS="cortex/auto"
MODEL_SONNET="nvidia_nim/deepseek-ai/deepseek-v4-pro"
MODEL_HAIKU="lmstudio/gemma-4-E4B-it-MLX-8bit"
```

## Architecture Notes

- **No state persistence** — brain override is process-scoped (resets on container restart)
- **No quota tracking** — unlike 9Router, Cortex doesn't track token budgets; it routes by complexity, not remaining quota
- **Fallback is error-based** — Cortex falls back when a provider throws an exception (timeout, 429, 404, etc.), not proactively
- **Sub-provider registry** — Cortex maintains its own provider registry separate from the main app registry to avoid circular lookups
- **Import boundaries** — Cortex internals are only accessible via `providers.registry` re-exports; `api/` never imports `providers.cortex` directly (enforced by contract tests)

## Ports Summary

| Port | Container | Provider | Use |
|---|---|---|---|
| 8082 | `fcc-proxy` | NVIDIA NIM direct | Production stable |
| 8083 | `fcc-cortex` | Cortex smart routing | Smart routing with LM Studio + NIM |

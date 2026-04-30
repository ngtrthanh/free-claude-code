"""FastAPI route handlers."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from loguru import logger

from config.settings import Settings
from core.anthropic import get_token_count

from . import dependencies
from .dependencies import get_settings, require_api_key
from .models.anthropic import MessagesRequest, TokenCountRequest
from .models.responses import ModelResponse, ModelsListResponse
from .services import ClaudeProxyService

router = APIRouter()


SUPPORTED_CLAUDE_MODELS = [
    ModelResponse(
        id="claude-opus-4-20250514",
        display_name="Claude Opus 4",
        created_at="2025-05-14T00:00:00Z",
    ),
    ModelResponse(
        id="claude-sonnet-4-20250514",
        display_name="Claude Sonnet 4",
        created_at="2025-05-14T00:00:00Z",
    ),
    ModelResponse(
        id="claude-haiku-4-20250514",
        display_name="Claude Haiku 4",
        created_at="2025-05-14T00:00:00Z",
    ),
    ModelResponse(
        id="claude-3-opus-20240229",
        display_name="Claude 3 Opus",
        created_at="2024-02-29T00:00:00Z",
    ),
    ModelResponse(
        id="claude-3-5-sonnet-20241022",
        display_name="Claude 3.5 Sonnet",
        created_at="2024-10-22T00:00:00Z",
    ),
    ModelResponse(
        id="claude-3-haiku-20240307",
        display_name="Claude 3 Haiku",
        created_at="2024-03-07T00:00:00Z",
    ),
    ModelResponse(
        id="claude-3-5-haiku-20241022",
        display_name="Claude 3.5 Haiku",
        created_at="2024-10-22T00:00:00Z",
    ),
]

# Cortex virtual models — appear in the model list so clients can select them
CORTEX_MODELS = [
    ModelResponse(
        id="cortex-auto",
        display_name="Cortex (Auto)",
        created_at="2025-01-01T00:00:00Z",
    ),
    ModelResponse(
        id="cortex-local",
        display_name="Cortex (Local)",
        created_at="2025-01-01T00:00:00Z",
    ),
    ModelResponse(
        id="cortex-remote",
        display_name="Cortex (Remote)",
        created_at="2025-01-01T00:00:00Z",
    ),
    ModelResponse(
        id="cortex-smart",
        display_name="Cortex (Smart)",
        created_at="2025-01-01T00:00:00Z",
    ),
    ModelResponse(
        id="cortex-native",
        display_name="Cortex (Native)",
        created_at="2025-01-01T00:00:00Z",
    ),
]


def get_proxy_service(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> ClaudeProxyService:
    """Build the request service for route handlers."""
    return ClaudeProxyService(
        settings,
        provider_getter=lambda provider_type: dependencies.resolve_provider(
            provider_type, app=request.app, settings=settings
        ),
        token_counter=get_token_count,
    )


def _probe_response(allow: str) -> Response:
    """Return an empty success response for compatibility probes."""
    return Response(status_code=204, headers={"Allow": allow})


# =============================================================================
# Routes
# =============================================================================
@router.post("/v1/messages")
async def create_message(
    request: Request,
    request_data: MessagesRequest,
    service: ClaudeProxyService = Depends(get_proxy_service),
    _auth=Depends(require_api_key),
):
    """Create a message (always streaming)."""
    from api.client_detection import detect_client
    from core.request_context import current_client

    current_client.set(detect_client(request))
    return service.create_message(request_data)


@router.api_route("/v1/messages", methods=["HEAD", "OPTIONS"])
async def probe_messages(_auth=Depends(require_api_key)):
    """Respond to Claude compatibility probes for the messages endpoint."""
    return _probe_response("POST, HEAD, OPTIONS")


@router.post("/v1/messages/count_tokens")
async def count_tokens(
    request_data: TokenCountRequest,
    service: ClaudeProxyService = Depends(get_proxy_service),
    _auth=Depends(require_api_key),
):
    """Count tokens for a request."""
    return service.count_tokens(request_data)


@router.api_route("/v1/messages/count_tokens", methods=["HEAD", "OPTIONS"])
async def probe_count_tokens(_auth=Depends(require_api_key)):
    """Respond to Claude compatibility probes for the token count endpoint."""
    return _probe_response("POST, HEAD, OPTIONS")


@router.get("/")
async def root(
    settings: Settings = Depends(get_settings), _auth=Depends(require_api_key)
):
    """Root endpoint."""
    return {
        "status": "ok",
        "provider": settings.provider_type,
        "model": settings.model,
    }


@router.api_route("/", methods=["HEAD", "OPTIONS"])
async def probe_root(_auth=Depends(require_api_key)):
    """Respond to compatibility probes for the root endpoint."""
    return _probe_response("GET, HEAD, OPTIONS")


@router.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


@router.api_route("/health", methods=["HEAD", "OPTIONS"])
async def probe_health():
    """Respond to compatibility probes for the health endpoint."""
    return _probe_response("GET, HEAD, OPTIONS")


@router.get("/v1/models", response_model=ModelsListResponse)
async def list_models(_auth=Depends(require_api_key)):
    """List the Claude model ids this proxy advertises for compatibility."""
    all_models = SUPPORTED_CLAUDE_MODELS + CORTEX_MODELS
    return ModelsListResponse(
        data=all_models,
        first_id=all_models[0].id if all_models else None,
        has_more=False,
        last_id=all_models[-1].id if all_models else None,
    )


@router.post("/stop")
async def stop_cli(request: Request, _auth=Depends(require_api_key)):
    """Stop all CLI sessions and pending tasks."""
    handler = getattr(request.app.state, "message_handler", None)
    if not handler:
        # Fallback if messaging not initialized
        cli_manager = getattr(request.app.state, "cli_manager", None)
        if cli_manager:
            await cli_manager.stop_all()
            logger.info("STOP_CLI: source=cli_manager cancelled_count=N/A")
            return {"status": "stopped", "source": "cli_manager"}
        raise HTTPException(status_code=503, detail="Messaging system not initialized")

    count = await handler.stop_all_tasks()
    logger.info("STOP_CLI: source=handler cancelled_count={}", count)
    return {"status": "stopped", "cancelled_count": count}


# =============================================================================
# Cortex brain override
# =============================================================================
@router.post("/v1/cortex/brain")
async def set_cortex_brain(request: Request, _auth=Depends(require_api_key)):
    """Override Cortex routing brain for the current process.

    Body (JSON):
        {"brain": "local"}    — force local tier
        {"brain": "remote"}   — force remote tier
        {"brain": "smart"}    — force smart tier
        {"brain": "native"}   — force native tier
        {"brain": "auto"}     — restore automatic score-based routing
        {"brain": "nvidia_nim/deepseek-ai/deepseek-v4-pro"}  — force specific model

    Returns the active brain after the change.
    """
    from providers.registry import CORTEX_TIER_ORDER as TIER_ORDER
    from providers.registry import set_cortex_brain

    body = await request.json()
    brain = body.get("brain", "auto")

    if brain == "auto":
        await set_cortex_brain(None)
        logger.info("CORTEX: brain reset to auto")
        return {"brain": "auto", "mode": "automatic"}

    # Validate: must be a known tier or a provider/model string
    if brain not in TIER_ORDER and "/" not in brain:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid brain {brain!r}. Use a tier name {TIER_ORDER} or 'provider/model'.",
        )

    await set_cortex_brain(brain)
    mode = "tier" if brain in TIER_ORDER else "direct"
    return {"brain": brain, "mode": mode}


@router.get("/v1/cortex/brain")
async def get_cortex_brain(_auth=Depends(require_api_key)):
    """Return the current Cortex brain override."""
    from providers.registry import get_cortex_brain

    override = get_cortex_brain()
    return {
        "brain": override or "auto",
        "mode": "automatic" if override is None else "override",
    }


# =============================================================================
# Cortex control plane
# =============================================================================


@router.get("/v1/cortex/config")
async def get_cortex_config(_auth=Depends(require_api_key)):
    """Return full live Cortex control plane state."""
    from providers.registry import (
        get_cortex_brain as _get_brain,
        get_cortex_circuit_status as _get_circuits,
        get_cortex_control_plane as _get_cp,
    )
    from core.cortex_metrics import CortexMetrics

    cp = _get_cp()
    metrics = CortexMetrics.get()
    snap = await metrics.snapshot()
    # Use the already-pushed control_plane from metrics (populated after first request)
    # Fall back to a fresh snapshot with no tier_config defaults
    control_plane = snap.get("control_plane") or cp.snapshot(None)

    return {
        "control_plane": control_plane,
        "auto_circuits": _get_circuits(),
        "brain": _get_brain() or "auto",
    }


@router.post("/v1/cortex/config/thresholds")
async def set_cortex_thresholds(request: Request, _auth=Depends(require_api_key)):
    """Update score thresholds for one or more tiers.

    Body: {"local": 0, "remote": 25, "smart": 55, "native": 85}
    Pass null to reset a tier to its env default.
    """
    from providers.registry import get_cortex_control_plane as _get_cp

    body = await request.json()
    cp = _get_cp()
    updated = {}
    for tier, value in body.items():
        cp.set_threshold(tier, int(value) if value is not None else None)
        updated[tier] = value
    await _push_cp()
    return {"updated": updated}


@router.post("/v1/cortex/config/circuit/{key:path}")
async def set_cortex_circuit(
    key: str, request: Request, _auth=Depends(require_api_key)
):
    """Manually open or close a circuit for a provider/model.

    key: "provider_id/model_name" e.g. "lmstudio/google/gemma-4-e4b"
    Body: {"state": "open"} | {"state": "closed"} | {"state": "auto"}
    """
    from providers.registry import get_cortex_control_plane as _get_cp

    body = await request.json()
    state = body.get("state", "auto")
    cp = _get_cp()

    if state == "open":
        cp.force_circuit_open(key)
    elif state == "closed":
        cp.force_circuit_closed(key)
    else:
        cp.clear_circuit_override(key)

    await _push_cp()
    return {"key": key, "state": state}


@router.post("/v1/cortex/config/client-pin")
async def set_client_pin(request: Request, _auth=Depends(require_api_key)):
    """Pin a client to a tier or provider/model.

    Body: {"client": "hermes", "target": "smart"}
          {"client": "claude-code", "target": "nvidia_nim/deepseek-ai/deepseek-v4-pro"}
          {"client": "hermes", "target": null}  — clear pin
    """
    from providers.registry import get_cortex_control_plane as _get_cp

    body = await request.json()
    client = body.get("client", "")
    target = body.get("target")
    cp = _get_cp()

    if not client:
        raise HTTPException(status_code=400, detail="client is required")

    if target:
        cp.set_client_pin(client, target)
        await _push_cp()
        return {"client": client, "target": target}
    else:
        cp.clear_client_pin(client)
        await _push_cp()
        return {"client": client, "target": None}


async def _push_cp() -> None:
    from providers.registry import push_cortex_control_plane

    await push_cortex_control_plane()


@router.post("/v1/cortex/config/tier-models")
async def set_tier_models(request: Request, _auth=Depends(require_api_key)):
    """Override models for a tier at runtime.

    Body: {"tier": "smart", "models": ["nvidia_nim/deepseek-ai/deepseek-v4-pro"]}
          {"tier": "local", "models": null}  — reset to env default
    """
    from providers.registry import get_cortex_control_plane as _get_cp

    body = await request.json()
    tier = body.get("tier", "")
    models = body.get("models")
    cp = _get_cp()

    if not tier:
        raise HTTPException(status_code=400, detail="tier is required")

    cp.set_tier_models(tier, models)
    await _push_cp()
    return {"tier": tier, "models": models}


@router.post("/v1/cortex/config/fallback")
async def set_fallback(request: Request, _auth=Depends(require_api_key)):
    """Toggle fallback behavior.

    Body: {"ascending": true, "descending": false}
    """
    from providers.registry import get_cortex_control_plane as _get_cp

    body = await request.json()
    cp = _get_cp()
    cp.set_fallback(
        ascending=body.get("ascending"),
        descending=body.get("descending"),
    )
    await _push_cp()
    return {"ascending": body.get("ascending"), "descending": body.get("descending")}

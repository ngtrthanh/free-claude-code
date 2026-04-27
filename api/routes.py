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
    request_data: MessagesRequest,
    service: ClaudeProxyService = Depends(get_proxy_service),
    _auth=Depends(require_api_key),
):
    """Create a message (always streaming)."""
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
    from providers.registry import set_cortex_brain, CORTEX_TIER_ORDER as TIER_ORDER

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

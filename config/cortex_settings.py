"""Cortex smart-routing configuration.

All settings are optional — Cortex degrades gracefully when tiers are unconfigured.

Env vars
--------
CORTEX_LOCAL_MODELS   Comma-separated provider/model strings for the local tier.
                      Example: "lmstudio/gemma-4-E4B-it-MLX-8bit,ollama/llama3"

CORTEX_REMOTE_MODELS  Comma-separated provider/model strings for the remote tier.
                      Example: "open_router/meta-llama/llama-3.1-8b-instruct:free"

CORTEX_SMART_MODELS   Comma-separated provider/model strings for the smart tier.
                      Example: "nvidia_nim/deepseek-ai/deepseek-v4-pro"

CORTEX_NATIVE_MODELS  Comma-separated provider/model strings for the native tier.
                      Example: "open_router/anthropic/claude-opus-4"

CORTEX_THRESHOLD_LOCAL   Minimum score to use local tier  (default: 0)
CORTEX_THRESHOLD_REMOTE  Minimum score to use remote tier (default: 25)
CORTEX_THRESHOLD_SMART   Minimum score to use smart tier  (default: 55)
CORTEX_THRESHOLD_NATIVE  Minimum score to use native tier (default: 85)

CORTEX_FALLBACK_ASCENDING   Try smarter tiers on failure (default: true)
CORTEX_FALLBACK_DESCENDING  Try cheaper tiers on failure  (default: true)
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from config.settings import _env_files


class CortexSettings(BaseSettings):
    """Smart-routing tier configuration loaded from environment variables."""

    # ── Tier model lists (comma-separated provider/model strings) ──────────────
    cortex_local_models: str = Field(
        default="",
        validation_alias="CORTEX_LOCAL_MODELS",
        description="Local/free tier: comma-separated provider/model strings",
    )
    cortex_remote_models: str = Field(
        default="",
        validation_alias="CORTEX_REMOTE_MODELS",
        description="Remote cheap tier: comma-separated provider/model strings",
    )
    cortex_smart_models: str = Field(
        default="",
        validation_alias="CORTEX_SMART_MODELS",
        description="Smart cloud tier: comma-separated provider/model strings",
    )
    cortex_native_models: str = Field(
        default="",
        validation_alias="CORTEX_NATIVE_MODELS",
        description="Native Anthropic tier: comma-separated provider/model strings",
    )

    # ── Score thresholds ───────────────────────────────────────────────────────
    cortex_threshold_local: int = Field(
        default=0,
        validation_alias="CORTEX_THRESHOLD_LOCAL",
    )
    cortex_threshold_remote: int = Field(
        default=25,
        validation_alias="CORTEX_THRESHOLD_REMOTE",
    )
    cortex_threshold_smart: int = Field(
        default=55,
        validation_alias="CORTEX_THRESHOLD_SMART",
    )
    cortex_threshold_native: int = Field(
        default=85,
        validation_alias="CORTEX_THRESHOLD_NATIVE",
    )

    # ── Fallback behaviour ─────────────────────────────────────────────────────
    cortex_fallback_ascending: bool = Field(
        default=True,
        validation_alias="CORTEX_FALLBACK_ASCENDING",
    )
    cortex_fallback_descending: bool = Field(
        default=True,
        validation_alias="CORTEX_FALLBACK_DESCENDING",
    )

    model_config = SettingsConfigDict(
        env_file=_env_files(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

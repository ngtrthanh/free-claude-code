"""Detect upstream client from HTTP request headers.

Fingerprints:
- Claude Code: sends anthropic-beta header + user-agent with 'claude-code'
- Hermes: uses anthropic SDK (x-stainless-*) but no anthropic-beta
- OpenWebUI: python-httpx user-agent, no stainless headers
- Direct/curl: minimal headers
"""

from __future__ import annotations

from fastapi import Request

# Known client names
CLIENT_CLAUDE_CODE = "claude-code"
CLIENT_HERMES = "hermes"
CLIENT_OPEN_WEBUI = "open-webui"
CLIENT_DIRECT = "direct"
CLIENT_UNKNOWN = "unknown"


def detect_client(request: Request) -> str:
    """Return a short client identifier from request headers."""
    headers = request.headers

    ua = headers.get("user-agent", "").lower()
    auth = headers.get("authorization", "").lower()
    beta = headers.get("anthropic-beta", "")
    stainless = headers.get("x-stainless-package-version", "")

    # Claude Code: always sends anthropic-beta, user-agent contains 'claude'
    if "claude" in ua or beta:
        return CLIENT_CLAUDE_CODE

    # Hermes: uses anthropic SDK (stainless headers) but no beta header
    # Also detectable by its API key
    if stainless or "hermes" in ua or "hermes-fcc" in auth:
        return CLIENT_HERMES

    # OpenWebUI: python-httpx, no stainless, known API key
    if "httpx" in ua or "openwebui" in ua:
        return CLIENT_OPEN_WEBUI

    # curl / direct API call
    if "curl" in ua or not ua:
        return CLIENT_DIRECT

    return CLIENT_UNKNOWN

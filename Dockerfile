# syntax=docker/dockerfile:1
# ─────────────────────────────────────────────────────────────────────────────
# Stage 1: builder — install deps into an isolated venv
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.14-slim AS builder

WORKDIR /app

# Copy pre-generated locked requirements (produced on host via:
#   uv export --no-dev --no-emit-project --format requirements-txt -o requirements.txt)
# Regenerate when pyproject.toml dependencies change.
COPY requirements.txt .

# Create venv and install deps — plain pip avoids uv's Tokio signal socket
# which panics under AppArmor-restricted Docker build environments.
RUN python -m venv /app/.venv \
 && /app/.venv/bin/pip install --no-cache-dir -r requirements.txt

# ─────────────────────────────────────────────────────────────────────────────
# Stage 2: runtime — minimal image with only what's needed to run
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.14-slim AS runtime

# Non-root user for security
RUN groupadd --gid 1001 appgroup \
 && useradd --uid 1001 --gid appgroup --no-create-home appuser

WORKDIR /app

# Copy venv from builder (no pip, no build tools in final image)
COPY --from=builder /app/.venv /app/.venv

# Copy application source
COPY api/       api/
COPY cli/       cli/
COPY config/    config/
COPY core/      core/
COPY messaging/ messaging/
COPY providers/ providers/
COPY server.py  .

# Give the non-root user write access to /app for logs and runtime files
RUN chown -R appuser:appgroup /app

# Activate venv by prepending to PATH
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Tell the app not to look for a .env file (config via env vars / mounted secret)
    FCC_ENV_FILE=""

# Default port (override with PORT env var)
EXPOSE 8082

# Drop to non-root
USER appuser

# Health check — hits the /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT:-8082}/health')"

# Entrypoint: uvicorn from the venv
CMD ["uvicorn", "server:app", \
     "--host", "0.0.0.0", \
     "--port", "8082", \
     "--timeout-graceful-shutdown", "5"]

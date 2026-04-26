# syntax=docker/dockerfile:1
# Multi-stage ARM64 build for AgentCore Runtime deployment (ECR push).
# Uses uv for fast dependency installation.
# Exposes POST /invocations and GET /ping on port 8080.

# ── Builder stage ──────────────────────────────────────────────────────────────
FROM --platform=linux/arm64 ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

COPY pyproject.toml .
COPY src/ ./src/

RUN uv sync --no-dev

# ── Runtime stage ──────────────────────────────────────────────────────────────
FROM --platform=linux/arm64 python:3.12-slim AS runtime

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv

COPY src/ ./src/

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app"

EXPOSE 8080

CMD ["uvicorn", "src.orchestrator.main:app", "--host", "0.0.0.0", "--port", "8080"]

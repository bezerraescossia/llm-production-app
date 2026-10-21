# syntax=docker/dockerfile:1
ARG PYTHON_IMAGE=python:3.12-slim@sha256:cb33f7f771ecec2ef1225cf39b159591a040391bd73e4c01f00fdfc4c47611d2

FROM ${PYTHON_IMAGE} AS builder
COPY --from=ghcr.io/astral-sh/uv:0.9.24@sha256:816fdce3387ed2142e37d2e56e1b1b97ccc1ea87731ba199dc8a25c04e4997c5 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
# The service reads the contract version from contracts/v1/openapi.yaml next to src/.
COPY contracts ./contracts
RUN uv sync --frozen --no-dev

FROM ${PYTHON_IMAGE}
RUN useradd --system --uid 10001 --no-create-home app
WORKDIR /app
COPY --from=builder --chown=app:app /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 SHUTDOWN_GRACE_SECONDS=20
USER app
EXPOSE 8080
HEALTHCHECK --interval=5s --timeout=3s --start-period=10s --retries=10 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/v1/health/live', timeout=2)"]
# Exec form via sh so SHUTDOWN_GRACE_SECONDS is expanded; exec keeps Uvicorn as PID 1 for SIGTERM.
CMD ["sh", "-c", "exec uvicorn ai_services.main:get_app --factory --host 0.0.0.0 --port 8080 --timeout-graceful-shutdown ${SHUTDOWN_GRACE_SECONDS}"]

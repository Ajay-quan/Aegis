# syntax=docker/dockerfile:1.7
# One image for api, worker, and dispatcher; the command selects the role.
FROM python:3.12.11-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock README.md ./
COPY packages/sdk-python packages/sdk-python
RUN uv sync --frozen --no-dev --no-install-project
COPY packages/core packages/core
COPY migrations migrations
COPY alembic.ini ./
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12.11-slim-bookworm
# Apply Debian security updates at build time (the base tag lags behind them).
RUN apt-get update && apt-get -y upgrade && apt-get install -y --no-install-recommends libpq5 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
RUN groupadd --system --gid 10001 aegis && useradd --system --uid 10001 --gid aegis --no-create-home aegis
WORKDIR /app
COPY --from=build --chown=root:root /app/.venv /app/.venv
COPY --from=build --chown=root:root /app/migrations /app/migrations
COPY --from=build --chown=root:root /app/alembic.ini /app/alembic.ini
ENV PATH=/app/.venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "aegistrace.api.app:build_from_env", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]

# syntax=docker/dockerfile:1.7
# AegisMem API image: multi-stage, non-root, no build tools at runtime.

FROM python:3.12-slim AS build
WORKDIR /src
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
COPY adapters ./adapters
COPY apps ./apps
COPY core ./core
COPY domain ./domain
COPY services ./services
COPY infra ./infra
RUN python -m venv /opt/venv && /opt/venv/bin/pip install ".[otel,llm]"

FROM python:3.12-slim AS runtime
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=production PYTHONPATH=/app
RUN groupadd --system --gid 10001 aegis && useradd --system --uid 10001 --gid aegis aegis
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY --chown=aegis:aegis adapters ./adapters
COPY --chown=aegis:aegis apps ./apps
COPY --chown=aegis:aegis core ./core
COPY --chown=aegis:aegis domain ./domain
COPY --chown=aegis:aegis services ./services
COPY --chown=aegis:aegis scripts ./scripts
COPY --chown=aegis:aegis infra/migrations ./infra/migrations
COPY --chown=aegis:aegis alembic.ini ./
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=2).status==200 else 1)"
# One worker per container; scale with replicas. Proxy headers for TLS-terminating ingress.
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]

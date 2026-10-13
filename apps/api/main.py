"""AegisMem FastAPI application."""
from __future__ import annotations

import asyncio
import inspect
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.config import settings
from core.logging.logger import setup_logging, new_request_id, set_context
from apps.api.routers import router
from apps.api.eval_router import eval_router
from apps.api.admin_router import admin_router
from apps.api.auth import authorize, require_admin
from apps.api.routing import route_template
from apps.api.security import install_security
from adapters.tenancy import TenantViolation
from core.exceptions import LLMError, MemoryNotFoundError
from core.version import ENGINE_NAME, PRODUCT_NAME, __version__
from core.observability.metrics import HTTP_LATENCY, HTTP_REQUESTS, REGISTRY
from core.observability.tracing import setup_tracing, tracer
from opentelemetry.propagate import extract
from opentelemetry.trace import SpanKind
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from apps.api.schemas import HealthResponse

setup_logging(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"AegisMem starting up (env={settings.app_env})")
    validate_runtime_config()
    setup_tracing()
    try:
        from apps.api.control import get_control_store
        from apps.api.dependencies import get_raw_db_store, get_raw_vector_store, get_graph_store
        await get_control_store()
        # Fail fast on a model/index dimension mismatch (would otherwise corrupt the index).
        from apps.api.dependencies import get_embedding
        probe = await get_embedding().embed_single("dimension probe")
        if len(probe) != settings.embedding_dimension:
            raise RuntimeError(f"embedding model returns {len(probe)} dims but EMBEDDING_DIMENSION="
                               f"{settings.embedding_dimension}")
        db = await get_raw_db_store()
        if settings.is_production_like and settings.require_rls and hasattr(db, "rls_effective"):
            ok, why = await db.rls_effective()
            if not ok:
                raise RuntimeError(f"Row-level security would be bypassed: {why}. Connect as a "
                                   "non-superuser role without BYPASSRLS (or set REQUIRE_RLS=false).")
        await get_raw_vector_store()
        await get_graph_store()
        logger.info("All stores initialized successfully")
        if settings.outbox_worker_enabled:
            from apps.api.dependencies import get_embedding
            from services.vector_sync import OutboxWorker
            worker = OutboxWorker(await get_control_store(), await get_raw_db_store(),
                                  await get_raw_vector_store(), get_embedding(),
                                  max_attempts=settings.outbox_max_attempts)
            app.state.outbox_task = asyncio.create_task(
                worker.run_forever(settings.outbox_interval_seconds,
                                   ledger_hours=settings.ledger_retention_hours,
                                   idempotency_hours=settings.idempotency_retention_hours))
    except Exception as e:
        if settings.is_production_like:
            raise  # fail closed: never serve without durable stores
        logger.warning(f"Store initialization warning: {e}")
    yield
    logger.info("AegisMem shutting down")
    task = getattr(app.state, "outbox_task", None)
    if task is not None:
        task.cancel()
    try:
        from apps.api.dependencies import _db_store, _graph_store
        if _db_store:
            await _db_store.close()
        if _graph_store:
            await _graph_store.close()
    except Exception:
        pass


def validate_runtime_config() -> None:
    """Refuse to boot staging/production with unsafe settings."""
    if not settings.is_production_like:
        if not settings.auth_enabled:
            logger.warning("AUTH DISABLED (development only): all requests act as tenant "
                           f"'{settings.default_tenant}' with every scope")
        return
    problems = []
    if not settings.auth_enabled:
        problems.append("AUTH_ENABLED must be true")
    if settings.app_secret_key in ("", "dev-secret-key", "change-me-in-production", "your-secret-key-change-in-production"):
        problems.append("APP_SECRET_KEY must be set to a strong secret")
    if not settings.api_key_pepper:
        problems.append("API_KEY_PEPPER must be set (separate from APP_SECRET_KEY)")
    if settings.default_llm_provider == "mock":
        problems.append("DEFAULT_LLM_PROVIDER=mock returns fabricated results; configure a real LLM")
    if settings.embedding_backend == "mock":
        problems.append("EMBEDDING_BACKEND=mock produces meaningless vectors; configure a real backend")
    for name in ("memory_backend", "vector_backend", "graph_backend"):
        if getattr(settings, name) == "memory":
            problems.append(f"{name.upper()}=memory is development-only")
    if problems:
        raise RuntimeError("Unsafe configuration: " + "; ".join(problems))


def create_app() -> FastAPI:
    app = FastAPI(
        title=f"{PRODUCT_NAME} - the trust layer for agent memory",
        description=(
            "Production-grade persistent memory system for long-running LLM agents. "
            "Supports multi-store hybrid retrieval, versioned updates, contradiction detection, "
            "and higher-level reflection generation."
        ),
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    install_security(app)

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request tracing middleware
    @app.middleware("http")
    async def trace_middleware(request: Request, call_next):
        request_id = new_request_id()
        start = time.time()
        with tracer.start_as_current_span(
            f"HTTP {request.method}", context=extract(request.headers), kind=SpanKind.SERVER,
        ) as span:
            response = await call_next(request)
            route = route_template(request) or "unmatched"  # template, not raw path
            span.update_name(f"{request.method} {route}")
            span.set_attributes({"http.request.method": request.method, "http.route": route,
                                 "http.response.status_code": response.status_code,
                                 "aegis.request_id": request_id})
            ctx = span.get_span_context()
            if ctx.is_valid:
                response.headers["X-Trace-Id"] = format(ctx.trace_id, "032x")
        duration_ms = (time.time() - start) * 1000
        HTTP_REQUESTS.labels(request.method, route, str(response.status_code)).inc()
        HTTP_LATENCY.labels(request.method, route).observe(duration_ms / 1000)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{duration_ms:.1f}ms"
        logger.info(
            f"{request.method} {request.url.path} -> {response.status_code} "
            f"({duration_ms:.1f}ms) rid={request_id}"
        )
        return response

    # Typed errors first. Cross-tenant access is indistinguishable from "not found".
    @app.exception_handler(MemoryNotFoundError)
    async def not_found_handler(request: Request, exc: MemoryNotFoundError):
        return JSONResponse(status_code=404, content={"detail": "memory not found"})

    @app.exception_handler(LLMError)
    async def llm_unavailable_handler(request: Request, exc: LLMError):
        logger.error(f"LLM error on {request.url.path}: {exc}")
        return JSONResponse(status_code=503, content={"error": {
            "code": "llm_unavailable", "message": str(exc)}})

    @app.exception_handler(TenantViolation)
    async def tenant_handler(request: Request, exc: TenantViolation):
        logger.warning(f"Tenant violation on {request.url.path}: {exc}")
        return JSONResponse(status_code=404, content={"detail": "not found"})

    # Exception handler
    @app.exception_handler(Exception)
    async def generic_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "type": type(exc).__name__},
        )

    # Health check
    @app.get("/health", response_model=HealthResponse, tags=["system"])
    async def health():
        return HealthResponse(
            status="ok",
            version=__version__,
            components={
                "api": "ok",
                "product": PRODUCT_NAME,
                "config": settings.app_env,
            },
        )

    @app.get("/ready", tags=["system"])
    async def ready():
        """Readiness: every durable dependency answers. Kubernetes should gate traffic on this."""
        from apps.api.control import get_control_store
        from apps.api.dependencies import get_raw_db_store
        checks: dict[str, str] = {}
        for name, probe in (("control_store", get_control_store), ("memory_store", get_raw_db_store)):
            try:
                store = app.dependency_overrides.get(probe, probe)()
                if inspect.isawaitable(store):
                    store = await store
                await store.ping()
                checks[name] = "ok"
            except Exception as e:  # report, don't raise: readiness must always answer
                checks[name] = f"error: {type(e).__name__}"
        ok = all(v == "ok" for v in checks.values())
        return JSONResponse(status_code=200 if ok else 503,
                            content={"status": "ready" if ok else "not_ready", "checks": checks})

    @app.get("/metrics", tags=["system"], include_in_schema=False)
    async def metrics():
        """Prometheus scrape endpoint. Expose only on the internal network (see deploy docs)."""
        if not settings.metrics_enabled:
            return Response(status_code=404)
        return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)

    @app.get("/", tags=["system"])
    async def root():
        return {
            "name": PRODUCT_NAME,
            "engine": ENGINE_NAME,
            "version": __version__,
            "description": "Persistent Memory Architecture for LLM Agents",
            "docs": "/docs",
            "health": "/health",
        }

    # Mount memory API routes
    app.include_router(router, prefix="/api/v1", tags=["memory"],
                       dependencies=[Depends(authorize)])
    app.include_router(admin_router, prefix="/api/v1/admin", tags=["admin"])
    app.include_router(eval_router, prefix="/api/v1/eval", tags=["evaluation"],
                       dependencies=[Depends(require_admin)])

    return app


app = create_app()

"""OpenTelemetry tracing. Disabled unless OTEL_ENABLED=true; when disabled every span is a
no-op from the API's default provider, so instrumentation costs nothing.

Span attributes carry ids, counts and decision enums only, never memory content or user text.
OTLP export needs the ``otel`` extra (``pip install aegismem[otel]``); endpoint and headers come
from the standard OTEL_EXPORTER_OTLP_* environment variables.
"""
from __future__ import annotations

import logging
from typing import Any

from opentelemetry import trace

from core.config.settings import settings

logger = logging.getLogger(__name__)
tracer = trace.get_tracer("aegismem")
_configured = False


def setup_tracing(exporter: Any | None = None) -> bool:
    """Install a TracerProvider once per process. Returns True if tracing is active."""
    global _configured
    if _configured:
        return True
    if not settings.otel_enabled and exporter is None:
        return False
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor

    provider = TracerProvider(resource=Resource.create({
        "service.name": settings.otel_service_name, "deployment.environment": settings.app_env}))
    if exporter is not None:  # tests / custom pipelines
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    elif settings.otel_exporter == "console":
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    else:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        except ImportError as e:
            raise RuntimeError("OTEL_ENABLED with otlp exporter requires `pip install aegismem[otel]`") from e
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    _configured = True
    logger.info(f"OpenTelemetry tracing enabled ({settings.otel_exporter})")
    return True

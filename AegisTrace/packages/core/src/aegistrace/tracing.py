# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""OpenTelemetry tracing for the API, dispatcher hand-off, workers, policy,
tools, models, MCP and memory.

One trace follows a run from the API request that created it, through the
outbox and queue, to the worker that executes it and every tool and model call
it makes (W3C trace context travels in the outbox message).

Spans carry identifiers and outcomes (run, tenant, tool, decision, risk class,
model id, latency), never payload content: no inputs, arguments, outputs or
model text. Tracing is off unless configured, and failing exporters never
affect requests.

Enable with standard OpenTelemetry settings:
  OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4318   (OTLP/HTTP)
  OTEL_SERVICE_NAME (default: aegistrace-<role>)
  AEGIS_TRACING=console   print spans to stderr instead (development)
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from opentelemetry import context, propagate, trace
from opentelemetry.trace import Span, SpanKind, Status, StatusCode

tracer = trace.get_tracer("aegistrace")
TRACEPARENT = "traceparent"
_configured = False


def configure(role: str, env: Mapping[str, str] | None = None) -> bool:
    """Install an exporting tracer provider when configured. Returns whether tracing is on."""
    global _configured
    e = os.environ if env is None else env
    mode = e.get("AEGIS_TRACING", "")
    endpoint = e.get("OTEL_EXPORTER_OTLP_ENDPOINT") or e.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    if _configured or (not endpoint and mode != "console") or mode == "off":
        return _configured
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SpanExporter

    exporter: SpanExporter
    if mode == "console":
        exporter = ConsoleSpanExporter()
    else:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter()  # reads the standard OTEL_EXPORTER_OTLP_* settings
    provider = TracerProvider(
        resource=Resource.create({"service.name": e.get("OTEL_SERVICE_NAME", f"aegistrace-{role}")})
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _configured = True
    return True


def inject() -> dict[str, str]:
    """The current trace context as W3C headers, for the outbox message."""
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return {k: v for k, v in carrier.items() if k in (TRACEPARENT, "tracestate")}


@contextmanager
def span(
    name: str,
    attributes: Mapping[str, Any] | None = None,
    kind: SpanKind = SpanKind.INTERNAL,
    parent: Mapping[str, str] | None = None,
) -> Iterator[Span]:
    """A span; with `parent` (W3C headers), continue that remote trace. Exceptions are recorded and re-raised."""
    token = context.attach(propagate.extract(dict(parent))) if parent else None
    try:
        with tracer.start_as_current_span(
            name, kind=kind, attributes={k: v for k, v in (attributes or {}).items() if v is not None}
        ) as s:
            yield s
    finally:
        if token is not None:
            context.detach(token)


def fail(s: Span, reason: str) -> None:
    s.set_status(Status(StatusCode.ERROR, reason))


class TraceContextFilter(logging.Filter):
    """Adds trace_id/span_id to log records, so logs and traces link up."""

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = trace.get_current_span().get_span_context()
        if ctx.is_valid:
            record.trace_id = format(ctx.trace_id, "032x")
            record.span_id = format(ctx.span_id, "016x")
        return True

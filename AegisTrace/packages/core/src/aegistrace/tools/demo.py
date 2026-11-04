# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Demonstration tools. Side effects go to an in-process DemoSink so tests can
prove whether an action happened. None of these touch real external systems
except http.fetch, which goes through the egress controls."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from . import egress
from .registry import Classification, RiskClass, ToolContext, ToolRegistry, ToolSpec


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


@dataclass
class DemoSink:
    """Records every side effect performed by demo tools."""

    effects: list[dict[str, Any]] = field(default_factory=list)
    documents: dict[str, dict[str, str]] = field(default_factory=dict)  # tenant -> doc_id -> text
    allowed_hosts_fetch: Any = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record(self, **effect: Any) -> None:
        with self._lock:
            self.effects.append(effect)


class CalcArgs(Strict):
    a: int
    b: int


class CalcOut(Strict):
    sum: int


class SearchArgs(Strict):
    query: str = Field(max_length=200)


class SearchOut(Strict):
    doc_ids: list[str]


class ReadArgs(Strict):
    doc_id: str = Field(pattern=r"^[a-z0-9_-]{1,64}$")


class ReadOut(Strict):
    doc_id: str
    text: str


class ExportArgs(Strict):
    dataset: str = Field(pattern=r"^[a-z0-9_-]{1,64}$")
    destination: str = Field(pattern=r"^[a-z0-9_.@-]{1,128}$")
    classification: str = Field(pattern=r"^(PUBLIC|INTERNAL|CONFIDENTIAL|RESTRICTED)$")


class ExportOut(Strict):
    export_id: str


class EmailArgs(Strict):
    to: str = Field(pattern=r"^[^@\s]{1,64}@[a-z0-9.-]{1,190}$")
    subject: str = Field(max_length=200)
    body: str = Field(max_length=10_000)


class EmailOut(Strict):
    message_id: str


class CodeArgs(Strict):
    code: str = Field(max_length=64 * 1024)


class CodeOut(Strict):
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool


class FetchArgs(Strict):
    url: str = Field(max_length=2048)


class FetchOut(Strict):
    status: int
    body: str


def build_registry(
    sink: DemoSink,
    resolver: egress.Resolver = egress.system_resolver,
    fetch_hosts: set[str] | None = None,
    sandbox: Any = None,
) -> ToolRegistry:
    """sandbox: a DockerSandbox; `code.run` is only registered when one is supplied
    (i.e. on a dedicated sandbox host)."""
    reg = ToolRegistry()

    def calc(ctx: ToolContext, a: CalcArgs) -> CalcOut:
        return CalcOut(sum=a.a + a.b)

    def search(ctx: ToolContext, a: SearchArgs) -> SearchOut:
        docs = sink.documents.get(ctx.tenant_id, {})
        q = a.query.lower()
        return SearchOut(doc_ids=sorted(d for d, t in docs.items() if q in t.lower()))

    def read(ctx: ToolContext, a: ReadArgs) -> ReadOut:
        text = sink.documents.get(ctx.tenant_id, {}).get(a.doc_id)
        if text is None:
            raise LookupError("document not found")
        return ReadOut(doc_id=a.doc_id, text=text)

    def export(ctx: ToolContext, a: ExportArgs) -> ExportOut:
        sink.record(
            kind="export",
            tenant_id=ctx.tenant_id,
            run_id=ctx.run_id,
            dataset=a.dataset,
            destination=a.destination,
            idempotency_key=ctx.idempotency_key,
        )
        return ExportOut(export_id="exp_" + ctx.idempotency_key[-12:])

    def email(ctx: ToolContext, a: EmailArgs) -> EmailOut:
        sink.record(
            kind="email", tenant_id=ctx.tenant_id, run_id=ctx.run_id, to=a.to, idempotency_key=ctx.idempotency_key
        )
        return EmailOut(message_id="msg_" + ctx.idempotency_key[-12:])

    def fetch(ctx: ToolContext, a: FetchArgs) -> FetchOut:
        status, body = egress.fetch(a.url, fetch_hosts or set(), resolver)
        return FetchOut(status=status, body=body[:65536].decode("utf-8", "replace"))

    reg.register(ToolSpec("calc.add", "Add two integers", RiskClass.PURE, CalcArgs, CalcOut, calc, True))
    reg.register(
        ToolSpec(
            "docs.search", "Search tenant documents", RiskClass.CONTROLLED_READ, SearchArgs, SearchOut, search, True
        )
    )
    reg.register(
        ToolSpec(
            "docs.read",
            "Read a tenant document",
            RiskClass.CONTROLLED_READ,
            ReadArgs,
            ReadOut,
            read,
            True,
            output_classification=Classification.CONFIDENTIAL,
            resource_of=lambda a: {"doc_id": a.doc_id},
        )
    )
    reg.register(
        ToolSpec(
            "data.export",
            "Export a dataset",
            RiskClass.CONSEQUENTIAL_WRITE,
            ExportArgs,
            ExportOut,
            export,
            False,
            resource_of=lambda a: {"dataset": a.dataset, "destination": a.destination},
            classification_of=lambda a: Classification[a.classification],
        )
    )
    reg.register(
        ToolSpec(
            "email.send",
            "Send an email",
            RiskClass.IRREVERSIBLE,
            EmailArgs,
            EmailOut,
            email,
            False,
            resource_of=lambda a: {"to": a.to},
        )
    )
    reg.register(
        ToolSpec(
            "http.fetch",
            "Fetch an allowlisted HTTPS URL",
            RiskClass.CONTROLLED_READ,
            FetchArgs,
            FetchOut,
            fetch,
            True,
            network=True,
            resource_of=lambda a: {"host": (urlsplit(a.url).hostname or "").lower()},
        )
    )
    if sandbox is not None:

        def run_code(ctx: ToolContext, a: CodeArgs) -> CodeOut:
            r = sandbox.run_python(a.code)
            return CodeOut(exit_code=r.exit_code, stdout=r.stdout, stderr=r.stderr[-4096:], timed_out=r.timed_out)

        reg.register(
            ToolSpec(
                "code.run",
                "Run Python in an isolated sandbox",
                RiskClass.PURE,
                CodeArgs,
                CodeOut,
                run_code,
                True,
                output_classification=Classification.CONFIDENTIAL,
            )
        )
    return reg

# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""AegisTrace REST API v1.

Every protected route: authenticate (JWT) -> require scope -> open a
transaction bound to the token's tenant (RLS). Cross-tenant identifiers
resolve to 404, indistinguishable from nonexistent ones.
"""

import logging
import os
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated, Any, Literal

import redis
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError, OperationalError

from aegisguard.authorization import rules as rules_mod
from aegisguard.identity.jwt import AuthError, JwksCache, Principal, TokenValidator
from aegisruntime.approvals import service as approvals
from aegisruntime.orchestration import service as runs
from aegisruntime.orchestration.states import TERMINAL, IllegalTransition, RunState
from aegisruntime.persistence.db import make_engine, tenant_tx
from aegisruntime.replay.engine import reconstruct, replay_decisions
from aegistrace.evidence.bundle import write_bundle_records
from aegistrace.evidence.signing import Signer, b64

from .settings import Settings

log = logging.getLogger("aegistrace.api")

ID = r"^[a-z]{3}_[a-f0-9]{24}$"
IDEMPOTENCY_KEY = re.compile(r"\A[A-Za-z0-9_.:-]{8,128}\Z")


# -- schemas -------------------------------------------------------------------


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectIn(Strict):
    name: str = Field(min_length=1, max_length=100)


class AgentIn(Strict):
    project_id: str = Field(pattern=ID)
    name: str = Field(min_length=1, max_length=100)
    model_provider: str = Field(default="mock", pattern=r"^(mock|openai-compatible)$")
    model_id: str = Field(default="mock-deterministic-1", max_length=100)


class GrantIn(Strict):
    tool: str = Field(pattern=r"^[a-z0-9_.]{1,64}$")
    max_risk_class: int = Field(ge=0, le=4)
    allowed_hosts: list[str] = Field(default_factory=list, max_length=50)


class RunIn(Strict):
    agent_id: str = Field(pattern=ID)
    input: dict[str, Any]


class DecisionIn(Strict):
    approve: bool


class ReconcileIn(Strict):
    outcome: str = Field(pattern="^(SUCCEEDED|FAILED|QUEUED)$")
    note: str = Field(default="", max_length=1000)


class SimulateIn(Strict):
    agent_id: str = Field(pattern=ID)
    tool: str = Field(pattern=r"^[a-z0-9_.]{1,128}$")
    arguments: dict[str, Any] = Field(default_factory=dict)


class RulesIn(Strict):
    rules: rules_mod.OrgRules
    source: Literal["dashboard", "api"] = "api"
    note: str | None = Field(default=None, max_length=500)


class ForkIn(Strict):
    reason: str = Field(min_length=1, max_length=500)


# -- app state -------------------------------------------------------------------


@dataclass
class Deps:
    engine: Engine
    validator: TokenValidator
    signer: Signer
    redis: Any
    rate_limit_per_minute: int = 600
    expose_metrics: bool = False
    gateway: Any = None  # ToolGateway, used only for policy dry runs (never executes)


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def create_app(deps: Deps) -> FastAPI:
    app = FastAPI(title="AegisTrace API", version="0.1.0", docs_url="/docs", redoc_url=None)
    app.state.deps = deps

    @app.exception_handler(HTTPException)
    async def http_exc(_: Request, exc: HTTPException) -> JSONResponse:
        code = {401: "unauthenticated", 403: "forbidden", 404: "not_found", 409: "conflict", 429: "rate_limited"}.get(
            exc.status_code, "error"
        )
        resp = _error(exc.status_code, code, str(exc.detail))
        if exc.status_code == 401:
            resp.headers["WWW-Authenticate"] = "Bearer"
        return resp

    @app.exception_handler(RequestValidationError)
    async def validation_exc(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Field locations only; never echo submitted values back.
        fields = [".".join(str(p) for p in e["loc"]) for e in exc.errors()]
        return _error(422, "invalid_request", f"invalid fields: {', '.join(fields[:10])}")

    @app.exception_handler(OperationalError)
    async def db_down(_: Request, exc: OperationalError) -> JSONResponse:
        log.error("database unavailable")
        return _error(503, "unavailable", "service temporarily unavailable")

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error")
        return _error(500, "internal_error", "internal error")

    # -- dependencies --------------------------------------------------------

    def principal(authorization: Annotated[str | None, Header()] = None) -> Principal:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(401, "missing bearer token")
        try:
            p = deps.validator.validate(authorization[7:].strip())
        except AuthError as exc:
            log.info("authentication failed", extra={"reason": str(exc)})
            raise HTTPException(401, "invalid token") from exc
        if p.token_id is not None:
            try:
                revoked = deps.redis.exists(f"revoked:{p.token_id}")
            except redis.RedisError as exc:
                # Revocation status unknown: fail closed (INV-012).
                log.error("revocation store unavailable")
                raise HTTPException(503, "authentication temporarily unavailable") from exc
            if revoked:
                raise HTTPException(401, "invalid token")
        _rate_limit(p)
        return p

    def _rate_limit(p: Principal) -> None:
        window = int(time.time() // 60)
        key = f"rl:{p.tenant_id}:{p.subject}:{window}"
        try:
            n = deps.redis.incr(key)
            if n == 1:
                deps.redis.expire(key, 120)
        except redis.RedisError:
            log.warning("rate limiter unavailable; allowing request")  # availability control, not authz
            return
        if n > deps.rate_limit_per_minute:
            raise HTTPException(429, "rate limit exceeded")

    def scoped(scope: str) -> Any:
        def dep(p: Annotated[Principal, Depends(principal)]) -> Principal:
            if not p.has(scope):
                raise HTTPException(403, f"missing scope {scope}")
            return p

        return Depends(dep)

    def tx(p: Principal) -> Iterator[Connection]:
        with tenant_tx(deps.engine, p.tenant_id) as conn:
            yield conn

    def actor(p: Principal) -> runs.Actor:
        return runs.Actor(p.subject, p.kind)

    # -- health ---------------------------------------------------------------

    if deps.expose_metrics:

        @app.get("/metrics", include_in_schema=False)
        def metrics() -> Response:
            # Off by default: platform-wide counters must not be reachable through the public ingress.
            from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

            return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    def readyz() -> JSONResponse:
        checks = {}
        try:
            with deps.engine.connect() as c:
                c.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except OperationalError:
            checks["database"] = "down"
        try:
            deps.redis.ping()
            checks["redis"] = "ok"
        except redis.RedisError:
            checks["redis"] = "down"
        ok = all(v == "ok" for v in checks.values())
        return JSONResponse({"status": "ok" if ok else "degraded", "checks": checks}, status_code=200 if ok else 503)

    # -- projects & agents ---------------------------------------------------------

    @app.post("/v1/projects", status_code=201)
    def create_project(body: ProjectIn, p: Principal = scoped("agents:write")) -> dict[str, Any]:
        from aegisruntime.persistence.admin import create_project as mk

        try:
            with tenant_tx(deps.engine, p.tenant_id) as c:
                return {"id": mk(c, p.tenant_id, body.name), "name": body.name}
        except IntegrityError as exc:
            raise HTTPException(409, "project name already exists") from exc

    @app.post("/v1/agents", status_code=201)
    def create_agent(body: AgentIn, p: Principal = scoped("agents:write")) -> dict[str, Any]:
        from aegisruntime.persistence.admin import create_agent as mk

        try:
            with tenant_tx(deps.engine, p.tenant_id) as c:
                aid = mk(c, p.tenant_id, body.project_id, body.name, body.model_provider, body.model_id)
        except IntegrityError as exc:
            raise HTTPException(409, "agent already exists or project not found") from exc
        return {"id": aid, **body.model_dump()}

    @app.get("/v1/agents")
    def list_agents(p: Principal = scoped("agents:read")) -> dict[str, Any]:
        with tenant_tx(deps.engine, p.tenant_id) as c:
            rows = (
                c.execute(text("SELECT id, project_id, name, model_provider, model_id FROM agents ORDER BY created_at"))
                .mappings()
                .all()
            )
        return {"items": [dict(r) for r in rows]}

    @app.put("/v1/agents/{agent_id}/grants", status_code=200)
    def put_grant(agent_id: str, body: GrantIn, p: Principal = scoped("policies:write")) -> dict[str, Any]:
        if p.kind != "user":
            raise HTTPException(403, "grants are administered by users")
        with tenant_tx(deps.engine, p.tenant_id) as c:
            if c.execute(text("SELECT 1 FROM agents WHERE id=:a"), {"a": agent_id}).first() is None:
                raise HTTPException(404, "agent not found")
            c.execute(text("DELETE FROM tool_grants WHERE agent_id=:a AND tool=:t"), {"a": agent_id, "t": body.tool})
            c.execute(
                text(
                    "INSERT INTO tool_grants (tenant_id, agent_id, tool, max_risk_class, allowed_hosts, "
                    "granted_by) VALUES (:tn, :a, :t, :m, :h, :u)"
                ),
                {
                    "tn": p.tenant_id,
                    "a": agent_id,
                    "t": body.tool,
                    "m": body.max_risk_class,
                    "h": body.allowed_hosts,
                    "u": p.subject,
                },
            )
        log.info("grant updated", extra={"tenant": p.tenant_id, "agent": agent_id, "tool": body.tool, "by": p.subject})
        return {"agent_id": agent_id, **body.model_dump()}

    @app.get("/v1/agents/{agent_id}/grants")
    def list_grants(agent_id: str, p: Principal = scoped("agents:read")) -> dict[str, Any]:
        with tenant_tx(deps.engine, p.tenant_id) as c:
            if c.execute(text("SELECT 1 FROM agents WHERE id=:a"), {"a": agent_id}).first() is None:
                raise HTTPException(404, "agent not found")
            rows = (
                c.execute(
                    text(
                        "SELECT tool, max_risk_class, allowed_hosts, granted_by, created_at FROM tool_grants "
                        "WHERE agent_id=:a ORDER BY tool"
                    ),
                    {"a": agent_id},
                )
                .mappings()
                .all()
            )
        return {"items": [dict(r) for r in rows]}

    @app.delete("/v1/agents/{agent_id}/grants/{tool}", status_code=204)
    def delete_grant(agent_id: str, tool: str, p: Principal = scoped("policies:write")) -> Response:
        if p.kind != "user":
            raise HTTPException(403, "grants are administered by users")
        with tenant_tx(deps.engine, p.tenant_id) as c:
            n = c.execute(
                text("DELETE FROM tool_grants WHERE agent_id=:a AND tool=:t"), {"a": agent_id, "t": tool}
            ).rowcount
        if not n:
            raise HTTPException(404, "grant not found")
        log.info("grant revoked", extra={"tenant": p.tenant_id, "agent": agent_id, "tool": tool, "by": p.subject})
        return Response(status_code=204)

    @app.get("/v1/tools")
    def list_tools(_: Principal = scoped("agents:read")) -> dict[str, Any]:
        if deps.gateway is None:
            return {"items": []}
        return {
            "items": [
                {k: t[k] for k in ("name", "description", "risk_class")} for t in deps.gateway._registry.describe()
            ]
        }

    @app.post("/v1/policy/simulate")
    def simulate(body: SimulateIn, p: Principal = scoped("agents:read")) -> dict[str, Any]:
        """Dry run: what would the gateway decide right now? Records nothing, executes nothing."""
        if deps.gateway is None:
            raise HTTPException(503, "policy simulation not configured")
        with tenant_tx(deps.engine, p.tenant_id) as c:
            if c.execute(text("SELECT 1 FROM agents WHERE id=:a"), {"a": body.agent_id}).first() is None:
                raise HTTPException(404, "agent not found")
        return dict(
            deps.gateway.simulate(
                tenant_id=p.tenant_id, agent_id=body.agent_id, tool_name=body.tool, raw_args=body.arguments
            )
        )

    # -- organization rules -----------------------------------------------------------

    @app.get("/v1/rules")
    def get_rules(p: Principal = scoped("agents:read")) -> dict[str, Any]:
        with tenant_tx(deps.engine, p.tenant_id) as c:
            current, version = rules_mod.load(c)
        return {
            "rules": current.model_dump(),
            "version": version,
            "preset": rules_mod.preset_of(current),
            "presets": {
                k: {"rules": v.model_dump(), "description": rules_mod.PRESET_DESCRIPTIONS[k]}
                for k, v in rules_mod.PRESETS.items()
            },
        }

    @app.put("/v1/rules")
    def put_rules(body: RulesIn, p: Principal = scoped("policies:write")) -> dict[str, Any]:
        if p.kind != "user":
            raise HTTPException(403, "rules are administered by users")
        with tenant_tx(deps.engine, p.tenant_id) as c:
            version = rules_mod.save(c, p.tenant_id, body.rules, p.subject, body.source, body.note)
        log.info("org rules updated", extra={"tenant": p.tenant_id, "version": version, "by": p.subject})
        return {"rules": body.rules.model_dump(), "version": version, "preset": rules_mod.preset_of(body.rules)}

    @app.get("/v1/rules/history")
    def rules_history(p: Principal = scoped("agents:read")) -> dict[str, Any]:
        with tenant_tx(deps.engine, p.tenant_id) as c:
            rows = (
                c.execute(
                    text(
                        "SELECT version, settings, changed_by, source, note, created_at "
                        "FROM tenant_rules_history ORDER BY version DESC LIMIT 50"
                    )
                )
                .mappings()
                .all()
            )
        return {"items": [dict(r) for r in rows]}

    @app.get("/v1/rules/file")
    def export_rules_file(p: Principal = scoped("agents:read")) -> Response:
        with tenant_tx(deps.engine, p.tenant_id) as c:
            current, _ = rules_mod.load(c)
            grants: dict[str, list[dict[str, Any]]] = {}
            for aid, tool, m, hosts in c.execute(
                text("SELECT agent_id, tool, max_risk_class, allowed_hosts FROM tool_grants ORDER BY agent_id, tool")
            ):
                g: dict[str, Any] = {"tool": tool, "max_risk_class": m}
                if hosts:
                    g["allowed_hosts"] = list(hosts)
                grants.setdefault(aid, []).append(g)
        return Response(
            rules_mod.export_yaml(current, grants),
            media_type="application/yaml",
            headers={"Content-Disposition": 'attachment; filename="aegistrace-rules.yaml"'},
        )

    @app.post("/v1/rules/file")
    async def apply_rules_file(
        request: Request, p: Principal = scoped("policies:write"), dry_run: bool = Query(False)
    ) -> dict[str, Any]:
        """Apply a YAML rules file: org rules plus the complete grant list for each agent named in it."""
        if p.kind != "user":
            raise HTTPException(403, "rules are administered by users")
        raw = (await request.body())[: 256 * 1024 + 1]
        try:
            doc = rules_mod.parse_rules_file(raw.decode("utf-8"))
            resolved = doc.resolved()
        except (ValueError, UnicodeDecodeError) as exc:
            msg = str(exc).splitlines()[0][:300]
            raise HTTPException(422, f"invalid rules file: {msg}") from exc
        changes: list[str] = []
        with tenant_tx(deps.engine, p.tenant_id) as c:
            current, _ = rules_mod.load(c)
            if current != resolved:
                changes.append("organization rules")
            known = {r[0] for r in c.execute(text("SELECT id FROM agents"))}
            unknown = sorted(set(doc.agents) - known)
            if unknown:
                raise HTTPException(422, f"unknown agent ids: {', '.join(unknown[:5])}")
            for aid, specs in doc.agents.items():
                existing = {
                    r[0]: (r[1], sorted(r[2]))
                    for r in c.execute(
                        text("SELECT tool, max_risk_class, allowed_hosts FROM tool_grants WHERE agent_id=:a"),
                        {"a": aid},
                    )
                }
                wanted = {g.tool: (g.max_risk_class, sorted(g.allowed_hosts)) for g in specs}
                for t in sorted(set(existing) - set(wanted)):
                    changes.append(f"revoke {t} from {aid}")
                for t, v in sorted(wanted.items()):
                    if existing.get(t) != v:
                        changes.append(f"grant {t} (class <= {v[0]}) to {aid}")
            if not dry_run and changes:
                if "organization rules" in changes:
                    rules_mod.save(c, p.tenant_id, resolved, p.subject, "file", "applied from rules file")
                for aid, specs in doc.agents.items():
                    c.execute(text("DELETE FROM tool_grants WHERE agent_id=:a"), {"a": aid})
                    for g in specs:
                        c.execute(
                            text(
                                "INSERT INTO tool_grants (tenant_id, agent_id, tool, max_risk_class, allowed_hosts, "
                                "granted_by) VALUES (:t, :a, :tool, :m, :h, :u)"
                            ),
                            {
                                "t": p.tenant_id,
                                "a": aid,
                                "tool": g.tool,
                                "m": g.max_risk_class,
                                "h": g.allowed_hosts,
                                "u": p.subject,
                            },
                        )
        log.info("rules file applied", extra={"tenant": p.tenant_id, "changes": len(changes), "dry_run": dry_run})
        return {"dry_run": dry_run, "changes": changes, "rules": resolved.model_dump()}

    @app.get("/v1/insights")
    def insights(
        p: Principal = scoped("runs:read"), range_: str = Query("7d", alias="range", pattern="^(24h|7d|30d)$")
    ) -> dict[str, Any]:
        from aegistrace.insights import build_report

        span = {"24h": "24 hours", "7d": "7 days", "30d": "30 days"}[range_]
        with tenant_tx(deps.engine, p.tenant_id) as c:
            report = build_report(c, span)
        return {"range": range_, **report}

    @app.post("/v1/auth/logout", status_code=204)
    def logout(p: Annotated[Principal, Depends(principal)]) -> Response:
        """Revoke the presented token until it would have expired anyway."""
        if p.token_id:
            deps.redis.set(f"revoked:{p.token_id}", "1", ex=24 * 3600)
        return Response(status_code=204)

    # -- runs --------------------------------------------------------------------

    @app.post("/v1/runs", status_code=201)
    def submit_run(
        body: RunIn, response: Response, idempotency_key: Annotated[str, Header()], p: Principal = scoped("runs:write")
    ) -> dict[str, Any]:
        if not IDEMPOTENCY_KEY.match(idempotency_key):
            raise HTTPException(422, "invalid Idempotency-Key")
        try:
            with tenant_tx(deps.engine, p.tenant_id) as c:
                run_id, created = runs.create_run(c, p.tenant_id, body.agent_id, body.input, actor(p), idempotency_key)
        except runs.NotFound as exc:
            raise HTTPException(404, "agent not found") from exc
        except runs.Conflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except runs.QuotaExceeded as exc:
            raise HTTPException(429, "concurrent run quota exceeded") from exc
        if not created:
            response.status_code = 200
        return {"id": run_id, "created": created}

    RUN_COLS = "id, agent_id, project_id, state, attempt, last_sequence, head_hash, result, created_at, updated_at"

    @app.get("/v1/runs")
    def list_runs(
        p: Principal = scoped("runs:read"),
        state: RunState | None = None,
        limit: int = Query(50, ge=1, le=200),
        cursor: str | None = None,
    ) -> dict[str, Any]:
        sql = f"SELECT {RUN_COLS} FROM runs WHERE (CAST(:st AS text) IS NULL OR state = CAST(:st AS text)) "  # noqa: S608
        if cursor:
            sql += "AND id < :cur "
        sql += "ORDER BY id DESC LIMIT :n"
        with tenant_tx(deps.engine, p.tenant_id) as c:
            rows = (
                c.execute(text(sql), {"st": state.value if state else None, "cur": cursor, "n": limit + 1})
                .mappings()
                .all()
            )
        items = [dict(r) for r in rows[:limit]]
        return {"items": items, "next_cursor": items[-1]["id"] if len(rows) > limit else None}

    def _get_run(c: Connection, run_id: str) -> dict[str, Any]:
        row = c.execute(text(f"SELECT {RUN_COLS} FROM runs WHERE id=:r"), {"r": run_id}).mappings().one_or_none()  # noqa: S608
        if row is None:
            raise HTTPException(404, "run not found")
        return dict(row)

    @app.get("/v1/runs/{run_id}")
    def get_run(run_id: str, p: Principal = scoped("runs:read")) -> dict[str, Any]:
        with tenant_tx(deps.engine, p.tenant_id) as c:
            return _get_run(c, run_id)

    def _can_see_payloads(p: Principal) -> bool:
        return p.has("payloads:read")

    def _events(c: Connection, run_id: str, p: Principal) -> list[dict[str, Any]]:
        records = runs.load_events(c, run_id)
        if not _can_see_payloads(p):
            for r in records:
                r.pop("payload", None)  # digest-only view: still verifiable (ADR-003)
        return records

    @app.get("/v1/runs/{run_id}/events")
    def get_events(run_id: str, p: Principal = scoped("runs:read")) -> dict[str, Any]:
        with tenant_tx(deps.engine, p.tenant_id) as c:
            _get_run(c, run_id)
            return {"items": _events(c, run_id, p), "payloads_included": _can_see_payloads(p)}

    @app.post("/v1/runs/{run_id}/cancel")
    def cancel(run_id: str, p: Principal = scoped("runs:write")) -> dict[str, Any]:
        with tenant_tx(deps.engine, p.tenant_id) as c:
            _get_run(c, run_id)
            try:
                c.execute(text("UPDATE runs SET fencing_token = fencing_token + 1 WHERE id=:r"), {"r": run_id})
                runs.transition(c, run_id, RunState.CANCELLED, actor(p), {"reason": "cancelled_by_user"})
            except IllegalTransition as exc:
                raise HTTPException(409, f"run cannot be cancelled from {exc.current}") from exc
        return {"id": run_id, "state": "CANCELLED"}

    @app.post("/v1/runs/{run_id}/reconcile")
    def reconcile(run_id: str, body: ReconcileIn, p: Principal = scoped("runs:reconcile")) -> dict[str, Any]:
        target, note = body.outcome, body.note
        with tenant_tx(deps.engine, p.tenant_id) as c:
            _get_run(c, run_id)
            try:
                runs.transition(c, run_id, RunState(target), actor(p), {"reconciliation_note": note})
            except (IllegalTransition, runs.OperatorRequired) as exc:
                raise HTTPException(409, str(exc)) from exc
        return {"id": run_id, "state": target}

    # -- receipts ------------------------------------------------------------------

    @app.post("/v1/runs/{run_id}/checkpoints", status_code=201)
    def make_checkpoint(run_id: str, p: Principal = scoped("receipts:export")) -> dict[str, Any]:
        with tenant_tx(deps.engine, p.tenant_id) as c:
            _get_run(c, run_id)
            return runs.checkpoint(c, run_id, deps.signer)

    @app.get("/v1/runs/{run_id}/receipt")
    def receipt(run_id: str, p: Principal = scoped("receipts:export")) -> Response:
        with tenant_tx(deps.engine, p.tenant_id) as c:
            _get_run(c, run_id)
            cp = runs.checkpoint(c, run_id, deps.signer)
            records = _events(c, run_id, p)
            cps = [
                dict(r)
                for (r,) in c.execute(
                    text("SELECT record FROM checkpoints WHERE run_id=:r ORDER BY last_sequence"), {"r": run_id}
                )
            ]
        bundle = write_bundle_records(p.tenant_id, run_id, records, cps or [cp], {})
        log.info(
            "receipt exported",
            extra={"tenant": p.tenant_id, "run": run_id, "by": p.subject, "payloads": _can_see_payloads(p)},
        )
        return Response(
            bundle,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{run_id}.receipt.zip"'},
        )

    @app.get("/v1/signing-keys")
    def signing_keys(_: Principal = scoped("runs:read")) -> dict[str, Any]:
        return {
            "keys": [
                {"key_id": deps.signer.key_id, "algorithm": "Ed25519", "public_key": b64(deps.signer.public_key_raw())}
            ],
            "note": "Obtain trust anchors out of band; do not trust this endpoint alone.",
        }

    @app.get("/v1/runs/{run_id}/verification")
    def verification(run_id: str, p: Principal = scoped("runs:read")) -> dict[str, Any]:
        """Convenience check run by the server against its own signing key.
        NOT independent verification (INV-010): use the offline verifier with a
        trust store obtained out of band for that."""
        from aegistrace.evidence.trust import TrustStore
        from aegistrace.evidence.verifier import verify_bundle

        with tenant_tx(deps.engine, p.tenant_id) as c:
            _get_run(c, run_id)
            cp = runs.checkpoint(c, run_id, deps.signer)
            records = runs.load_events(c, run_id)
        bundle = write_bundle_records(p.tenant_id, run_id, records, [cp], {})
        trust = TrustStore.from_json(
            {
                "version": 1,
                "keys": [
                    {
                        "key_id": deps.signer.key_id,
                        "public_key": b64(deps.signer.public_key_raw()),
                        "not_before": "1970-01-01T00:00:00Z",
                    }
                ],
            }
        )
        report = verify_bundle(bundle, trust, p.tenant_id, run_id).as_dict()
        report["independent"] = False
        report["checkpoint"] = cp["body"]
        return report

    @app.get("/v1/stats")
    def stats(p: Principal = scoped("runs:read")) -> dict[str, Any]:
        with tenant_tx(deps.engine, p.tenant_id) as c:
            by_state: dict[str, int] = dict(c.execute(text("SELECT state, count(*) FROM runs GROUP BY state")).all())
            pending = c.execute(
                text("SELECT count(*) FROM approvals WHERE status='pending' AND expires_at > now()")
            ).scalar_one()
            denials = c.execute(
                text(
                    "SELECT count(*) FROM policy_decisions WHERE decision='deny' "
                    "AND created_at > now() - interval '24 hours'"
                )
            ).scalar_one()
            lat = c.execute(
                text(
                    "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY ms), percentile_cont(0.95) WITHIN GROUP "
                    "(ORDER BY ms) FROM (SELECT EXTRACT(EPOCH FROM updated_at - created_at) * 1000 AS ms FROM runs "
                    "WHERE state = 'SUCCEEDED' AND updated_at > now() - interval '24 hours') t"
                )
            ).one()
        return {
            "runs_by_state": by_state,
            "pending_approvals": pending,
            "policy_denials_24h": denials,
            "run_duration_ms_24h": {"p50": lat[0], "p95": lat[1]},
        }

    RANGES = {"1h": ("1 hour", "1 minute"), "24h": ("24 hours", "30 minutes"), "7d": ("7 days", "4 hours")}

    @app.get("/v1/stats/timeseries")
    def timeseries(
        p: Principal = scoped("runs:read"), range_: str = Query("1h", alias="range", pattern="^(1h|24h|7d)$")
    ) -> dict[str, Any]:
        """Bucketed counts for charts: runs finished by outcome, tool decisions by result."""
        span, step = RANGES[range_]
        with tenant_tx(deps.engine, p.tenant_id) as c:
            rows = c.execute(
                text(
                    """
                WITH b AS (
                  SELECT generate_series(date_bin(CAST(:step AS interval), now() - CAST(:span AS interval),
                                                  TIMESTAMPTZ '2000-01-01'),
                                         now(), CAST(:step AS interval)) AS t
                ), r AS (
                  SELECT date_bin(CAST(:step AS interval), updated_at, TIMESTAMPTZ '2000-01-01') AS t,
                         count(*) FILTER (WHERE state = 'SUCCEEDED') AS succeeded,
                         count(*) FILTER (WHERE state IN ('FAILED', 'TIMED_OUT', 'NEEDS_RECONCILIATION')) AS failed
                  FROM runs WHERE updated_at > now() - CAST(:span AS interval) GROUP BY 1
                ), d AS (
                  SELECT date_bin(CAST(:step AS interval), created_at, TIMESTAMPTZ '2000-01-01') AS t,
                         count(*) FILTER (WHERE decision = 'allow') AS allowed,
                         count(*) FILTER (WHERE decision = 'deny') AS denied,
                         count(*) FILTER (WHERE decision = 'require_approval') AS approval
                  FROM policy_decisions WHERE created_at > now() - CAST(:span AS interval) GROUP BY 1
                )
                SELECT b.t, COALESCE(r.succeeded, 0), COALESCE(r.failed, 0), COALESCE(d.allowed, 0),
                       COALESCE(d.denied, 0), COALESCE(d.approval, 0)
                FROM b LEFT JOIN r USING (t) LEFT JOIN d USING (t) ORDER BY b.t
                """
                ),
                {"span": span, "step": step},
            ).all()
        return {
            "range": range_,
            "step": step,
            "points": [
                {"t": t.isoformat(), "succeeded": s_, "failed": f, "allowed": a, "denied": dn, "approval": ap}
                for t, s_, f, a, dn, ap in rows
            ],
        }

    @app.get("/v1/policy-decisions")
    def policy_decisions(
        p: Principal = scoped("audit:read"),
        decision: str | None = Query(None, pattern="^(allow|deny|require_approval)$"),
        limit: int = Query(100, ge=1, le=500),
    ) -> dict[str, Any]:
        with tenant_tx(deps.engine, p.tenant_id) as c:
            rows = (
                c.execute(
                    text(
                        "SELECT decision_id, run_id, principal, tool, resource, policy_revision, decision, reason, "
                        "input_digest, created_at FROM policy_decisions WHERE (CAST(:d AS text) IS NULL OR decision = "
                        "CAST(:d AS text)) ORDER BY created_at DESC LIMIT :n"
                    ),
                    {"d": decision, "n": limit},
                )
                .mappings()
                .all()
            )
        return {"items": [dict(r) for r in rows]}

    # -- approvals ------------------------------------------------------------------

    @app.get("/v1/approvals")
    def list_approvals(
        p: Principal = scoped("approvals:read"),
        status: str = Query("pending", pattern="^(pending|approved|rejected|consumed|expired)$"),
    ) -> dict[str, Any]:
        with tenant_tx(deps.engine, p.tenant_id) as c:
            rows = (
                c.execute(
                    text(
                        "SELECT id, run_id, agent_id, tool, risk_class, resource, summary, status, expires_at, "
                        "requested_at, decided_by FROM approvals WHERE status = :s ORDER BY requested_at DESC LIMIT 200"
                    ),
                    {"s": status},
                )
                .mappings()
                .all()
            )
        return {"items": [dict(r) for r in rows]}

    @app.post("/v1/approvals/{approval_id}/decision")
    def decide(approval_id: str, body: DecisionIn, p: Principal = scoped("approvals:decide")) -> dict[str, Any]:
        try:
            with tenant_tx(deps.engine, p.tenant_id) as c:
                status = approvals.decide(c, approval_id, actor(p), body.approve)
        except runs.NotFound as exc:
            raise HTTPException(404, "approval not found") from exc
        except approvals.ApprovalDenied as exc:
            raise HTTPException(403, str(exc)) from exc
        except runs.Conflict as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"id": approval_id, "status": status}

    # -- replay ------------------------------------------------------------------------

    @app.get("/v1/runs/{run_id}/replay")
    def replay(run_id: str, p: Principal = scoped("replay:read")) -> dict[str, Any]:
        with tenant_tx(deps.engine, p.tenant_id) as c:
            run = _get_run(c, run_id)
            records = runs.load_events(c, run_id)
        view = reconstruct(records).as_dict()
        decisions = replay_decisions(records)
        return {
            "reconstructed_state": view,
            "projection_state": run["state"],
            "state_matches_projection": view["state"] == run["state"],
            "decision_replay": decisions.as_dict()
            if p.has("payloads:read")
            else {"status": decisions.status.value, "steps_compared": decisions.steps_compared},
        }

    @app.post("/v1/runs/{run_id}/fork", status_code=201)
    def fork(
        run_id: str, body: ForkIn, idempotency_key: Annotated[str, Header()], p: Principal = scoped("replay:fork")
    ) -> dict[str, Any]:
        """Replay D: a NEW execution seeded from a historical run's input."""
        if not IDEMPOTENCY_KEY.match(idempotency_key):
            raise HTTPException(422, "invalid Idempotency-Key")
        if not p.has("runs:write"):
            raise HTTPException(403, "missing scope runs:write")
        with tenant_tx(deps.engine, p.tenant_id) as c:
            src = c.execute(
                text("SELECT agent_id, input, head_hash, last_sequence, state FROM runs WHERE id=:r"), {"r": run_id}
            ).one_or_none()
            if src is None:
                raise HTTPException(404, "run not found")
            if RunState(src[4]) not in TERMINAL:
                raise HTTPException(409, "can only fork a finished run")
            new_input = {
                **src[1],
                "forked_from": {"run_id": run_id, "head_hash": src[2], "last_sequence": src[3], "reason": body.reason},
            }
            new_id, created = runs.create_run(c, p.tenant_id, src[0], new_input, actor(p), idempotency_key)
        return {"id": new_id, "created": created, "forked_from": run_id}

    return app


def build_from_env() -> FastAPI:
    """Entry point for uvicorn: `uvicorn aegis_api.app:build_from_env --factory`."""
    from aegistrace.evidence.signing import load_local_signer
    from aegistrace.logging import configure

    configure()
    s = Settings.from_env()
    deps = Deps(
        engine=make_engine(s.database_url),
        validator=TokenValidator(s.oidc_issuer, s.oidc_audience, JwksCache(s.oidc_jwks)),
        signer=load_local_signer(
            s.signing_key_file, allow_shared_file=os.environ.get("AEGIS_DEV_ALLOW_SHARED_KEY_FILE") == "1"
        ),
        redis=redis.Redis.from_url(s.redis_url, decode_responses=True, socket_timeout=0.5),
        rate_limit_per_minute=int(os.environ.get("AEGIS_RATE_LIMIT_PER_MINUTE", "600")),
        expose_metrics=os.environ.get("AEGIS_API_METRICS") == "1",
    )
    from aegisguard.authorization.policy import OpaPolicyEngine
    from aegisruntime.tools.demo import DemoSink, build_registry
    from aegisruntime.tools.gateway import ToolGateway

    deps.gateway = ToolGateway(deps.engine, build_registry(DemoSink()), OpaPolicyEngine(s.opa_url))
    return create_app(deps)

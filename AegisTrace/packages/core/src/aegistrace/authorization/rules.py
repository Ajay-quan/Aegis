# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Per-organization rules: what needs approval, what is always blocked.

These settings are passed to OPA as `input.settings`; the Rego policy enforces
them. Grants (which agent may use which tool) stay per agent. Rules can be
edited in the dashboard, through the API, or applied from a YAML file
(`aegistrace policy apply rules.yaml`); every change is versioned in an
append-only history.
"""

from __future__ import annotations

import json
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Connection, text

TOOL = r"^[a-z0-9_.]{1,128}$"


class OrgRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_min_risk_class: int = Field(
        default=3, ge=1, le=4, description="Tools at or above this risk class need human approval"
    )
    restricted_data_requires_approval: bool = True
    blocked_tools: list[str] = Field(default_factory=list, max_length=200)
    always_require_approval: list[str] = Field(default_factory=list, max_length=200)
    approval_ttl_minutes: int = Field(default=60, ge=5, le=7 * 24 * 60)

    @field_validator("blocked_tools", "always_require_approval")
    @classmethod
    def _tools(cls, v: list[str]) -> list[str]:
        import re

        for t in v:
            if not re.match(TOOL, t):
                raise ValueError(f"invalid tool name: {t!r}")
        return sorted(set(v))


PRESETS: dict[str, OrgRules] = {
    "strict": OrgRules(approval_min_risk_class=2, approval_ttl_minutes=30),
    "balanced": OrgRules(),
    "permissive": OrgRules(approval_min_risk_class=4, approval_ttl_minutes=240),
}
PRESET_DESCRIPTIONS = {
    "strict": "Any action that changes something needs a human. Best while you are getting started.",
    "balanced": "Reads and small reversible changes run automatically; consequential actions need approval.",
    "permissive": "Only irreversible actions need approval. For mature, well-understood agents.",
}


def preset_of(r: OrgRules) -> str | None:
    for name, p in PRESETS.items():
        if p.model_dump() == r.model_dump():
            return name
    return None


def load(conn: Connection) -> tuple[OrgRules, int]:
    row = conn.execute(text("SELECT settings, version FROM tenant_rules")).one_or_none()
    if row is None:
        return OrgRules(), 0
    return OrgRules.model_validate(row[0]), int(row[1])


def save(
    conn: Connection,
    tenant_id: str,
    rules: OrgRules,
    actor: str,
    source: Literal["dashboard", "api", "file"],
    note: str | None = None,
) -> int:
    _, version = load(conn)
    new = version + 1
    doc = json.dumps(rules.model_dump())
    conn.execute(
        text(
            "INSERT INTO tenant_rules (tenant_id, settings, version, updated_by) "
            "VALUES (:t, CAST(:s AS jsonb), :v, :u) "
            "ON CONFLICT (tenant_id) DO UPDATE SET settings = EXCLUDED.settings, version = EXCLUDED.version, "
            "updated_by = EXCLUDED.updated_by, updated_at = now()"
        ),
        {"t": tenant_id, "s": doc, "v": new, "u": actor},
    )
    conn.execute(
        text(
            "INSERT INTO tenant_rules_history (tenant_id, version, settings, changed_by, source, note) "
            "VALUES (:t, :v, CAST(:s AS jsonb), :u, :src, :n)"
        ),
        {"t": tenant_id, "v": new, "s": doc, "u": actor, "src": source, "n": note},
    )
    return new


# -- rules as a file ----------------------------------------------------------------


class GrantSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str = Field(pattern=TOOL)
    max_risk_class: int = Field(ge=0, le=4)
    allowed_hosts: list[str] = Field(default_factory=list)


class RulesFile(BaseModel):
    """`version: 1`, optional `preset`, `rules` overrides, and `agents` grants by agent id."""

    model_config = ConfigDict(extra="forbid")
    version: Literal[1]
    preset: Literal["strict", "balanced", "permissive"] | None = None
    rules: dict[str, Any] = Field(default_factory=dict)
    agents: dict[str, list[GrantSpec]] = Field(default_factory=dict)

    def resolved(self) -> OrgRules:
        base = PRESETS[self.preset].model_dump() if self.preset else OrgRules().model_dump()
        return OrgRules.model_validate({**base, **self.rules})


def parse_rules_file(data: str) -> RulesFile:
    if len(data) > 256 * 1024:
        raise ValueError("rules file too large")
    try:
        doc = yaml.safe_load(data)  # safe_load: never constructs arbitrary Python objects
    except yaml.YAMLError as exc:
        raise ValueError(f"not valid YAML: {type(exc).__name__}") from exc
    if not isinstance(doc, dict):
        raise ValueError("rules file must be a mapping")
    return RulesFile.model_validate(doc)


def export_yaml(rules: OrgRules, grants: dict[str, list[dict[str, Any]]]) -> str:
    preset = preset_of(rules)
    doc: dict[str, Any] = {"version": 1}
    if preset:
        doc["preset"] = preset
    else:
        doc["rules"] = rules.model_dump()
    doc["agents"] = grants
    header = (
        "# AegisTrace rules for this organization.\n"
        "# Apply with: aegistrace policy apply <this file>\n"
        "# preset: strict | balanced | permissive. `rules:` overrides individual settings.\n"
        "# agents: <agent id> -> tools that agent may use (anything not listed is blocked).\n"
    )
    return header + yaml.safe_dump(doc, sort_keys=False)

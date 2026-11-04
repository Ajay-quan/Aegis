# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Server-side tool registry. Tool metadata (risk class, network use, retry
safety) is configured by the platform, never taken from the tool or model."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from pydantic import BaseModel


class RiskClass(IntEnum):
    PURE = 0
    CONTROLLED_READ = 1
    REVERSIBLE_WRITE = 2
    CONSEQUENTIAL_WRITE = 3
    IRREVERSIBLE = 4


class Classification(IntEnum):
    PUBLIC = 0
    INTERNAL = 1
    CONFIDENTIAL = 2
    RESTRICTED = 3


@dataclass(frozen=True)
class ToolContext:
    tenant_id: str
    run_id: str
    idempotency_key: str


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    risk_class: RiskClass
    args_model: type[BaseModel]
    output_model: type[BaseModel]
    execute: Callable[[ToolContext, Any], BaseModel]
    retry_safe: bool  # True only if re-execution with the same idempotency key is harmless
    network: bool = False
    output_classification: Classification = Classification.INTERNAL
    resource_of: Callable[[Any], dict[str, Any]] | None = None
    classification_of: Callable[[Any], Classification] | None = None


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"duplicate tool {spec.name}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def describe(self) -> list[dict[str, Any]]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "risk_class": int(t.risk_class),
                "parameters": t.args_model.model_json_schema(),
            }
            for t in self._tools.values()
        ]

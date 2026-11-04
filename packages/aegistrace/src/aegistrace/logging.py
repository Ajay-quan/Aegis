# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Structured JSON logging with secret redaction (INV-011)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

SECRET_PATTERNS = [
    re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]+"),
    re.compile(r"eyJ[a-zA-Z0-9_-]{5,}\.[a-zA-Z0-9_-]{5,}\.[a-zA-Z0-9_-]+"),  # JWT
    re.compile(r"(?i)(api[_-]?key|password|secret|token)\s*[=:]\s*\S+"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
]
SENSITIVE_KEYS = {"authorization", "password", "secret", "api_key", "token", "private_key", "cookie"}
STANDARD_ATTRS = set(vars(logging.makeLogRecord({})))


def redact(value: Any) -> Any:
    if isinstance(value, str):
        for p in SECRET_PATTERNS:
            value = p.sub("[REDACTED]", value)
        return value
    if isinstance(value, dict):
        return {k: "[REDACTED]" if str(k).lower() in SENSITIVE_KEYS else redact(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact(v) for v in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        out.update({k: v for k, v in vars(record).items() if k not in STANDARD_ATTRS})
        if record.exc_info:
            out["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
        return json.dumps(redact(out), default=str)


def configure(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)

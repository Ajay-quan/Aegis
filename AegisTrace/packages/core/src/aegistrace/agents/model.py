# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 AegisTrace contributors
"""Provider-neutral model interface.

MockModel is deterministic: it replays a script supplied in the run input.
That lets tests and demos model any agent behaviour, including malicious
tool proposals, without a paid provider.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx


@dataclass(frozen=True)
class ToolCall:
    tool: str
    arguments: Any


@dataclass(frozen=True)
class ModelResponse:
    tool_call: ToolCall | None
    text: str | None
    usage: dict[str, int] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return {
            "tool_call": {"tool": self.tool_call.tool, "arguments": self.tool_call.arguments}
            if self.tool_call
            else None,
            "text": self.text,
            "usage": self.usage,
        }

    @classmethod
    def from_record(cls, rec: dict[str, Any]) -> ModelResponse:
        tc = rec.get("tool_call")
        return cls(ToolCall(tc["tool"], tc["arguments"]) if tc else None, rec.get("text"), rec.get("usage") or {})


class ModelError(Exception):
    def __init__(self, classification: str) -> None:
        super().__init__(classification)
        self.classification = classification  # "timeout" | "rate_limited" | "provider_error" | "invalid_response"


class ModelAdapter(Protocol):
    provider: str
    model_id: str

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelResponse: ...


class MockModel:
    provider = "mock"
    model_id = "mock-deterministic-1"

    def __init__(self, script: list[dict[str, Any]]) -> None:
        self._script = script

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelResponse:
        step = sum(1 for m in messages if m["role"] == "assistant")
        if step >= len(self._script):
            return ModelResponse(None, "done")
        item = self._script[step]
        if "tool" in item:
            return ModelResponse(ToolCall(item["tool"], item.get("args", {})), None, {"tokens": 0})
        return ModelResponse(None, str(item.get("final", "")), {"tokens": 0})


class OpenAICompatibleModel:
    """Chat Completions-compatible adapter. The API key is held only here and
    never recorded; events capture digests of request and response."""

    provider = "openai-compatible"

    def __init__(
        self, base_url: str, api_key: str, model_id: str, timeout: float = 60.0, client: httpx.Client | None = None
    ) -> None:
        self.model_id = model_id
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._client = client or httpx.Client(timeout=timeout)

    def __repr__(self) -> str:
        return f"OpenAICompatibleModel(model_id={self.model_id!r})"

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelResponse:
        body = {
            "model": self.model_id,
            "messages": messages,
            "tools": [
                {
                    "type": "function",
                    "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]},
                }
                for t in tools
            ],
        }
        try:
            r = self._client.post(self._url, json=body, headers=self._headers)
        except httpx.TimeoutException as exc:
            raise ModelError("timeout") from exc
        except httpx.HTTPError as exc:
            raise ModelError("provider_error") from exc
        if r.status_code == 429:
            raise ModelError("rate_limited")
        if r.status_code != 200:
            raise ModelError("provider_error")
        try:
            data = r.json()
            msg = data["choices"][0]["message"]
            usage = {k: int(v) for k, v in (data.get("usage") or {}).items() if isinstance(v, int)}
            calls = msg.get("tool_calls") or []
            if calls:
                import json

                fn = calls[0]["function"]
                return ModelResponse(ToolCall(fn["name"], json.loads(fn["arguments"])), None, usage)
            return ModelResponse(None, msg.get("content") or "", usage)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ModelError("invalid_response") from exc


def timed(fn: Any, *args: Any) -> tuple[Any, int]:
    t0 = time.perf_counter()
    out = fn(*args)
    return out, int((time.perf_counter() - t0) * 1000)

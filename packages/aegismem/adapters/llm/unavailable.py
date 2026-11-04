"""Explicit "no LLM" client. Every call raises ``LLMError`` so LLM-dependent features fail
visibly (HTTP 503) instead of silently returning fabricated or default results."""
from __future__ import annotations

from typing import Any

from core.exceptions import LLMError

from .base import LLMClient


class UnavailableLLMClient(LLMClient):
    def __init__(self, reason: str) -> None:
        self.reason = reason

    def _fail(self) -> None:
        raise LLMError(f"LLM unavailable: {self.reason}")

    async def generate(self, prompt: str, system: str = "", temperature: float = 0.7,
                       max_tokens: int = 1024, **kwargs: Any):
        self._fail()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self._fail()

    async def classify(self, *args: Any, **kwargs: Any):
        self._fail()

    async def generate_json(self, *args: Any, **kwargs: Any):
        self._fail()

"""Provider-agnostic LLM interface for AegisMem."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMResponse:
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    finish_reason: str = "stop"
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def usage(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass
class ClassificationResponse:
    label: str
    confidence: float
    raw: dict[str, Any] = field(default_factory=dict)


class LLMClient(ABC):
    """Protocol-like base class for all LLM providers."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> LLMResponse: ...

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    async def classify(
        self, prompt: str, labels: list[str], **kwargs: Any
    ) -> ClassificationResponse:
        """Default classification via generation."""
        labels_str = ", ".join(labels)
        sys_prompt = (
            f"Classify the following text into exactly one of these labels: {labels_str}. "
            "Reply with only the label name, nothing else."
        )
        resp = await self.generate(prompt, system=sys_prompt, temperature=0.0, max_tokens=20)
        label = resp.content.strip()
        matched = next((l for l in labels if l.lower() == label.lower()), labels[0])
        return ClassificationResponse(label=matched, confidence=0.9, raw=resp.raw)

    async def generate_json(
        self, prompt: str, system: str = "", **kwargs: Any
    ) -> dict[str, Any]:
        """Generate and parse JSON response."""
        import json

        json_system = system + "\nRespond ONLY with valid JSON. No markdown, no explanation."
        resp = await self.generate(prompt, system=json_system, temperature=0.1, **kwargs)
        content = resp.content.strip()
        # Strip markdown fences if present
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0]
        return json.loads(content)

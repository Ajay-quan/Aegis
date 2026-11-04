"""Anthropic LLM client adapter."""
from __future__ import annotations

import logging
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential

from core.exceptions import LLMError, EmbeddingError
from .base import LLMClient, LLMResponse

logger = logging.getLogger(__name__)


class AnthropicClient(LLMClient):
    """Anthropic Claude API adapter."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-haiku-4-5-20251001",
        embedding_fallback_client: LLMClient | None = None,
    ) -> None:
        try:
            from anthropic import AsyncAnthropic
        except ImportError:
            raise ImportError("Install anthropic: pip install anthropic")

        self.model = model
        self._client = AsyncAnthropic(api_key=api_key)
        self._embedding_client = embedding_fallback_client

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    async def generate(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> LLMResponse:
        try:
            params: dict[str, Any] = {
                "model": self.model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [{"role": "user", "content": prompt}],
            }
            if system:
                params["system"] = system

            resp = await self._client.messages.create(**params)
            content = ""
            for block in resp.content:
                if hasattr(block, "text"):
                    content += block.text

            return LLMResponse(
                content=content,
                model=resp.model,
                prompt_tokens=resp.usage.input_tokens,
                completion_tokens=resp.usage.output_tokens,
                total_tokens=resp.usage.input_tokens + resp.usage.output_tokens,
                finish_reason=resp.stop_reason or "stop",
            )
        except Exception as e:
            logger.error(f"Anthropic generation error: {e}")
            raise LLMError(f"Anthropic error: {e}") from e

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if self._embedding_client:
            return await self._embedding_client.embed(texts)
        raise EmbeddingError(
            "Anthropic does not natively support embeddings. "
            "Provide an embedding_fallback_client."
        )

"""Ollama client adapter for local LLMs."""
from __future__ import annotations

import json
from typing import Any

import httpx

from core.exceptions import ConfigurationError
from .base import LLMClient, LLMResponse


class OllamaClient(LLMClient):
    """Client for local Ollama instances."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.2",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.generate_url = f"{self.base_url}/api/generate"
        self.embed_url = f"{self.base_url}/api/embeddings"

    async def generate(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate text using local Ollama model."""
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        
        # Pass through relevant kwargs to Ollama options
        for key in ["top_p", "top_k", "seed", "stop"]:
            if key in kwargs:
                payload["options"][key] = kwargs[key]

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.generate_url,
                    json=payload,
                    timeout=180.0,
                )
                response.raise_for_status()
            except httpx.HTTPError as e:
                raise Exception(f"Failed to communicate with Ollama: {e}")

        data = response.json()
        
        return LLMResponse(
            content=data.get("response", ""),
            model=data.get("model", self.model),
            prompt_tokens=data.get("prompt_eval_count", 0),
            completion_tokens=data.get("eval_count", 0),
            total_tokens=data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
            finish_reason=data.get("done_reason", "stop"),
            raw=data,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings using Ollama (if configured as embedding backend)."""
        embeddings = []
        async with httpx.AsyncClient() as client:
            for text in texts:
                try:
                    response = await client.post(
                        self.embed_url,
                        json={"model": self.model, "prompt": text},
                        timeout=60.0,
                    )
                    response.raise_for_status()
                    data = response.json()
                    embeddings.append(data.get("embedding", []))
                except httpx.HTTPError as e:
                    raise Exception(f"Failed to get embeddings from Ollama: {e}")
        
        return embeddings

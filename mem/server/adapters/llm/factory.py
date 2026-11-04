"""LLM client factory."""
from __future__ import annotations

from core.config import settings
from core.exceptions import ConfigurationError
from .base import LLMClient
from .mock_client import MockLLMClient


def create_llm_client(
    provider: str | None = None,
    model: str | None = None,
) -> LLMClient:
    """Create an LLM client based on configuration."""
    provider = provider or settings.default_llm_provider
    model = model or settings.default_llm_model

    if provider == "openai":
        if not settings.openai_api_key:
            raise ConfigurationError("OPENAI_API_KEY not set")
        from .openai_client import OpenAIClient
        return OpenAIClient(api_key=settings.openai_api_key, model=model)

    elif provider == "anthropic":
        if not settings.anthropic_api_key:
            raise ConfigurationError("ANTHROPIC_API_KEY not set")
        from .anthropic_client import AnthropicClient
        return AnthropicClient(api_key=settings.anthropic_api_key, model=model)

    elif provider == "local":
        from .ollama_client import OllamaClient
        return OllamaClient(base_url=settings.ollama_base_url, model=model)

    elif provider == "mock":
        return MockLLMClient()

    else:
        raise ConfigurationError(f"Unknown LLM provider: {provider}")

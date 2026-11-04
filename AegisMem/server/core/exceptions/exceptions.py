"""AegisMem custom exceptions."""


class StatefulError(Exception):
    """Base exception for AegisMem."""


class MemoryNotFoundError(StatefulError):
    def __init__(self, memory_id: str) -> None:
        super().__init__(f"Memory not found: {memory_id}")
        self.memory_id = memory_id


class MemoryStorageError(StatefulError):
    """Error in storage backend."""


class MemoryRetrievalError(StatefulError):
    """Error during retrieval."""


class EmbeddingError(StatefulError):
    """Error generating embeddings."""


class LLMError(StatefulError):
    """Error from LLM provider."""


class ContradictionError(StatefulError):
    """Error during contradiction detection."""


class ConfigurationError(StatefulError):
    """Invalid configuration."""


class NamespaceError(StatefulError):
    """Invalid or inaccessible namespace."""


class ValidationError(StatefulError):
    """Schema validation failure."""

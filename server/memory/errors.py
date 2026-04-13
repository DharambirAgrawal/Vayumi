from __future__ import annotations


class MemoryError(Exception):
    """Base class for memory-layer exceptions."""

    code = "memory_error"

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.details = details or {}


class MemoryValidationError(MemoryError):
    code = "memory_validation_error"


class MemoryIngestionError(MemoryError):
    code = "memory_ingestion_error"


class MemoryStoreError(MemoryError):
    code = "memory_store_error"


class MemoryRetrievalError(MemoryError):
    code = "memory_retrieval_error"


class MemoryTrainingError(MemoryError):
    code = "memory_training_error"

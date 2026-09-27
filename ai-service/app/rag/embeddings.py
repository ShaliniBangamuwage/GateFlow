"""Local open-source sentence embeddings and a transparent cosine utility."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Protocol

import numpy as np

DEFAULT_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


class TextEmbeddingModel(Protocol):
    def embed(self, texts: list[str]) -> Iterable[Sequence[float]]: ...

    def query_embed(self, text: str) -> Iterable[Sequence[float]]: ...


class EmbeddingProvider:
    """Small wrapper to keep model downloads/encoding outside request logic.

    The selected BGE small English model is open-source and local. Its actual
    output dimension is read from an encoded vector rather than trusted as a
    guessed pgvector schema constant.
    """

    def __init__(self, model_name: str = DEFAULT_EMBEDDING_MODEL, model: TextEmbeddingModel | None = None) -> None:
        self.model_name = model_name
        if model is None:
            import os

            from fastembed import TextEmbedding

            model = TextEmbedding(
                model_name=model_name,
                cache_dir=os.getenv("FASTEMBED_CACHE_DIR"),
            )
        self._model = model
        self._dimension: int | None = None

    @property
    def dimension(self) -> int | None:
        """The vector length after first inference; None before model execution."""
        return self._dimension

    def embed_text(self, text: str) -> list[float]:
        vectors = self.embed_documents([text])
        return vectors[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        cleaned = [_validate_text(text) for text in texts]
        if not cleaned:
            return []
        vectors = [np.asarray(vector, dtype=np.float32) for vector in self._model.embed(cleaned)]
        return self._validate_vectors(vectors, expected_count=len(cleaned))

    def embed_query(self, text: str) -> list[float]:
        cleaned = _validate_text(text)
        encoded = self._model.query_embed(QUERY_INSTRUCTION + cleaned)
        vector = np.asarray(next(iter(encoded)), dtype=np.float32)
        return self._validate_vectors([vector], expected_count=1)[0]

    def _validate_vectors(
        self, vectors: list[np.ndarray], *, expected_count: int
    ) -> list[list[float]]:
        if len(vectors) != expected_count:
            raise ValueError("embedding model returned an unexpected vector count")
        if not vectors:
            return []
        dimension = int(vectors[0].size)
        if dimension < 1 or any(vector.ndim != 1 or vector.size != dimension for vector in vectors):
            raise ValueError("embedding model returned inconsistent vector dimensions")
        if any(not np.isfinite(vector).all() for vector in vectors):
            raise ValueError("embedding model returned non-finite values")
        if self._dimension is not None and self._dimension != dimension:
            raise ValueError("embedding model dimension changed unexpectedly")
        self._dimension = dimension
        return [vector.astype(float).tolist() for vector in vectors]


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Return cosine similarity: dot(A,B) / (||A|| * ||B||)."""
    first = np.asarray(left, dtype=float)
    second = np.asarray(right, dtype=float)
    if first.ndim != 1 or second.ndim != 1 or first.shape != second.shape:
        raise ValueError("vectors must be one-dimensional and have equal lengths")
    if not np.isfinite(first).all() or not np.isfinite(second).all():
        raise ValueError("vectors must contain only finite values")
    denominator = float(np.linalg.norm(first) * np.linalg.norm(second))
    if denominator == 0:
        raise ValueError("cosine similarity is undefined for a zero vector")
    return float(np.dot(first, second) / denominator)


def _validate_text(text: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("embedding text must be a non-empty string")
    return text.strip()
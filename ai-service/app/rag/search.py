from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class KnowledgeSearchResult:
    tenant_id: str
    content: str
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)
    similarity: float = 0.0
    distance: float = 0.0


class EmbeddingLike(Protocol):
    def embed_query(self, text: str) -> list[float]: ...
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...


class InMemoryKnowledgeStore:
    def __init__(self, chunks: list[KnowledgeSearchResult] | None = None) -> None:
        self.chunks = list(chunks or [])

    def top_k(self, tenant_id: str, query_vector: list[float], limit: int = 5) -> list[KnowledgeSearchResult]:
        filtered = [chunk for chunk in self.chunks if chunk.tenant_id == tenant_id]
        scored = []
        for chunk in filtered:
            score = sum(a * b for a, b in zip(query_vector, chunk.metadata.get("vector", [0.0] * len(query_vector)), strict=False))
            scored.append((score, chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [chunk for _, chunk in scored[:limit]]


def search_knowledge_base(
    *,
    query: str,
    tenant_id: str,
    limit: int = 5,
    store: InMemoryKnowledgeStore | None = None,
    embedder: EmbeddingLike | None = None,
) -> list[KnowledgeSearchResult]:
    if not query.strip():
        raise ValueError("query must be a non-empty string")
    if not tenant_id.strip():
        raise ValueError("tenant_id is required")
    normalized_limit = max(1, int(limit))
    store = store or InMemoryKnowledgeStore()
    embedder = embedder or _IdentityEmbedding()
    query_vector = embedder.embed_query(query)
    results = store.top_k(tenant_id, query_vector, normalized_limit)
    return [
        KnowledgeSearchResult(
            tenant_id=result.tenant_id,
            content=result.content,
            source=result.source,
            metadata=result.metadata,
            similarity=result.similarity,
            distance=result.distance,
        )
        for result in results
    ]


def search_knowledge_base_pgvector(
    *,
    query: str,
    tenant_id: str,
    limit: int = 5,
    store: Any | None = None,
    embedder: EmbeddingLike | None = None,
) -> list[KnowledgeSearchResult]:
    if not query.strip():
        raise ValueError("query must be a non-empty string")
    if not tenant_id.strip():
        raise ValueError("tenant_id is required")
    if store is None:
        raise ValueError("pgvector store is required")
    if not hasattr(store, "search"):
        raise ValueError("pgvector store must implement search")
    normalized_limit = max(1, int(limit))
    embedder = embedder or _IdentityEmbedding()
    query_vector = embedder.embed_query(query)
    rows = store.search(tenant_id=tenant_id, query_vector=query_vector, limit=normalized_limit)
    normalized_rows: list[KnowledgeSearchResult] = []
    for row in rows:
        metadata = row.get("metadata") or {}
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except json.JSONDecodeError:
                metadata = {}
        normalized_rows.append(
            KnowledgeSearchResult(
                tenant_id=str(row.get("tenant_id", tenant_id)),
                content=str(row.get("content", "")),
                source=str(row.get("source_id") or row.get("source_name") or row.get("source") or "unknown"),
                metadata=dict(metadata),
                similarity=float(row.get("similarity", 0.0) or 0.0),
                distance=float(row.get("distance", 0.0) or 0.0),
            )
        )
    return normalized_rows


class _IdentityEmbedding:
    def embed_query(self, text: str) -> list[float]:
        return [1.0 if text.strip() else 0.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0 if text.strip() else 0.0] for text in texts]

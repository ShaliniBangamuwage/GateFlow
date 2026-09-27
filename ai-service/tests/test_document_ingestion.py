from __future__ import annotations

from pathlib import Path

import pytest

from app.rag.ingestion import ingest_document, safe_document_path
from app.rag.search import KnowledgeSearchResult, search_knowledge_base_pgvector


class FakeEmbedding:
    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0] if "too many requests" in text.lower() else [0.0, 1.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]


class FakeStore:
    def __init__(self) -> None:
        self.deleted: list[tuple[str, str]] = []
        self.inserted: list[list[dict[str, object]]] = []

    def delete_by_source(self, *, tenant_id: str, source_id: str, source_type: str = "document") -> None:
        self.deleted.append((tenant_id, source_id))

    def upsert_chunks(self, chunks: list[dict[str, object]]) -> None:
        self.inserted.append(list(chunks))


def test_safe_document_path_restricts_to_workspace_files() -> None:
    base = Path(__file__).resolve().parents[1]
    allowed = safe_document_path(base / "README.md", workspace_root=base)
    assert allowed == base / "README.md"

    with pytest.raises(ValueError, match="unsafe"):
        safe_document_path(base.parent / "secrets.txt", workspace_root=base)


def test_ingest_document_is_deduplicated_and_replaces_source_chunks() -> None:
    fake_store = FakeStore()
    doc = "# Rate limits\n\nHTTP 429 means the rate limit was exceeded. Clients should honor Retry-After."

    ingest_document(
        tenant_id="tenant-a",
        source_id="docs/rate-limits.md",
        source_name="Rate limits",
        content=doc,
        store=fake_store,
        embedder=FakeEmbedding(),
    )

    ingest_document(
        tenant_id="tenant-a",
        source_id="docs/rate-limits.md",
        source_name="Rate limits",
        content=doc,
        store=fake_store,
        embedder=FakeEmbedding(),
    )

    assert len(fake_store.inserted) == 2
    assert fake_store.deleted == [("tenant-a", "docs/rate-limits.md"), ("tenant-a", "docs/rate-limits.md")]
    assert all(chunk["tenant_id"] == "tenant-a" for chunk in fake_store.inserted[-1])


def test_pgvector_search_maps_rows_to_tenant_safe_semantic_results() -> None:
    class LookupStore:
        def search(self, *, tenant_id: str, query_vector: list[float], limit: int = 5):
            assert tenant_id == "tenant-a"
            return [
                {
                    "tenant_id": "tenant-a",
                    "content": "HTTP 429 means the rate limit was exceeded; clients should honor Retry-After.",
                    "source_name": "docs/rate-limits.md",
                    "metadata": {"section": "rate limiting"},
                    "similarity": 0.91,
                    "distance": 0.09,
                }
            ]

    results = search_knowledge_base_pgvector(
        query="Why am I receiving too many requests?",
        tenant_id="tenant-a",
        limit=5,
        store=LookupStore(),
        embedder=FakeEmbedding(),
    )

    assert len(results) == 1
    assert isinstance(results[0], KnowledgeSearchResult)
    assert results[0].source == "docs/rate-limits.md"
    assert results[0].tenant_id == "tenant-a"

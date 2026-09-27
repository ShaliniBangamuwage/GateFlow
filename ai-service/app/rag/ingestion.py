from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from app.rag.chunking import chunk_markdown
from app.rag.embeddings import EmbeddingProvider


class StoreLike(Protocol):
    def delete_by_source(self, *, tenant_id: str, source_id: str, source_type: str = "document") -> None: ...
    def upsert_chunks(self, chunks: list[dict[str, Any]]) -> None: ...


class EmbedderLike(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...


def safe_document_path(path: str | Path, *, workspace_root: str | Path) -> Path:
    root = Path(workspace_root).resolve()
    candidate = Path(path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("unsafe path: document must live under the workspace root") from exc
    return candidate


def ensure_safe_source(source_id: str) -> str:
    normalized = source_id.strip()
    if not normalized:
        raise ValueError("source_id is required")
    if any(token in normalized for token in ("..", "\\", "/../", "..\\")):
        raise ValueError("unsafe source_id")
    return normalized


def ingest_document(
    *,
    tenant_id: str,
    source_id: str,
    source_name: str,
    content: str,
    store: StoreLike,
    embedder: EmbedderLike | None = None,
    source_type: str = "document",
    workspace_root: str | Path | None = None,
) -> list[dict[str, Any]]:
    if not tenant_id.strip():
        raise ValueError("tenant_id is required")
    normalized_source_id = ensure_safe_source(source_id)
    normalized_name = (source_name or normalized_source_id).strip()
    if not normalized_name:
        raise ValueError("source_name is required")
    cleaned = _clean_document(content)
    if not cleaned.strip():
        raise ValueError("document content is empty")

    if workspace_root is not None:
        safe_document_path(normalized_source_id, workspace_root=workspace_root)

    chunks = chunk_markdown(cleaned)
    if not chunks:
        return []

    embedder = embedder or EmbeddingProvider()
    vectors = embedder.embed_documents([chunk.content for chunk in chunks])

    rows: list[dict[str, Any]] = []
    for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
        rows.append(
            {
                "tenant_id": tenant_id,
                "source_type": source_type,
                "source_id": normalized_source_id,
                "source_name": normalized_name,
                "section": chunk.section,
                "content": chunk.content,
                "chunk_index": index,
                "metadata": {"section": chunk.section, "source_name": normalized_name},
                "embedding": vector,
            }
        )

    store.delete_by_source(tenant_id=tenant_id, source_id=normalized_source_id, source_type=source_type)
    store.upsert_chunks(rows)
    return rows


def _clean_document(content: str) -> str:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = []
    for line in normalized.splitlines():
        cleaned = line.strip()
        if cleaned:
            lines.append(cleaned)
    return "\n\n".join(lines)

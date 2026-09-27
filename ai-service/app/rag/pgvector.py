from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Sequence

import psycopg

PGVECTOR_SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id BIGSERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'document',
    source_id TEXT NOT NULL,
    source_name TEXT NOT NULL,
    section TEXT NOT NULL DEFAULT 'Document',
    content TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    embedding VECTOR(384) NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, source_type, source_id, content_hash, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_tenant_id
    ON knowledge_chunks (tenant_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_source_id
    ON knowledge_chunks (tenant_id, source_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_lookup
    ON knowledge_chunks (tenant_id, source_type, source_id, content_hash, chunk_index);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_embedding
    ON knowledge_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
"""


class PgVectorKnowledgeStore:
    """pgvector-backed knowledge store for tenant-scoped retrieval."""

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn or os.getenv("AI_DATABASE_URL") or os.getenv("DATABASE_URL", "")

    def ensure_schema(self) -> None:
        if not self.dsn:
            raise ValueError("database connection string is required")
        with psycopg.connect(self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(PGVECTOR_SCHEMA_SQL)

    def upsert_chunks(self, chunks: list[dict[str, Any]]) -> None:
        if not chunks:
            return
        if not self.dsn:
            raise ValueError("database connection string is required")

        payload = []
        for chunk in chunks:
            source_id = str(chunk.get("source_id") or chunk.get("source") or chunk.get("source_name") or "unknown")
            source_name = str(chunk.get("source_name") or chunk.get("source") or source_id)
            section = str(chunk.get("section") or "Document")
            content = str(chunk["content"])
            metadata = dict(chunk.get("metadata") or {})
            embedding = list(chunk["embedding"])
            content_hash = _hash_content(content)
            payload.append(
                (
                    str(chunk["tenant_id"]),
                    str(chunk.get("source_type", "document")),
                    source_id,
                    source_name,
                    section,
                    content,
                    int(chunk["chunk_index"]),
                    json.dumps(metadata, sort_keys=True),
                    _vector_literal(embedding),
                    content_hash,
                )
            )

        with psycopg.connect(self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO knowledge_chunks (
                        tenant_id, source_type, source_id, source_name, section,
                        content, chunk_index, metadata, embedding, content_hash
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::vector, %s)
                    ON CONFLICT (tenant_id, source_type, source_id, content_hash, chunk_index)
                    DO UPDATE SET
                        source_name = EXCLUDED.source_name,
                        section = EXCLUDED.section,
                        content = EXCLUDED.content,
                        metadata = EXCLUDED.metadata,
                        embedding = EXCLUDED.embedding,
                        updated_at = NOW()
                    """,
                    payload,
                )

    def delete_by_source(self, *, tenant_id: str, source_id: str, source_type: str = "document") -> None:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id is required")
        if not self.dsn:
            raise ValueError("database connection string is required")
        with psycopg.connect(self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM knowledge_chunks WHERE tenant_id = %s AND source_type = %s AND source_id = %s",
                    (normalized_tenant, source_type, source_id),
                )

    def search(self, *, tenant_id: str, query_vector: list[float], limit: int = 5) -> list[dict[str, Any]]:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id is required")
        if not self.dsn:
            raise ValueError("database connection string is required")
        vector_sql = _vector_literal(query_vector)
        safe_limit = max(1, int(limit))
        with psycopg.connect(self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, tenant_id, source_type, source_id, source_name, section,
                           content, metadata, chunk_index,
                           1 - (embedding <=> %s::vector) AS similarity,
                           (embedding <=> %s::vector) AS distance
                    FROM knowledge_chunks
                    WHERE tenant_id = %s
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (vector_sql, vector_sql, normalized_tenant, vector_sql, safe_limit),
                )
                rows = cursor.fetchall()
                if not rows:
                    return []
                if not hasattr(cursor, "description") or cursor.description is None:
                    return [dict(row) if isinstance(row, dict) else row for row in rows]
                columns = [column.name for column in cursor.description]
                return [dict(zip(columns, row, strict=False)) for row in rows]


def _hash_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _vector_literal(values: Sequence[float]) -> str:
    items = ", ".join(str(float(value)) for value in values)
    return f"[{items}]"

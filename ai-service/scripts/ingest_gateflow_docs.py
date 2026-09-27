from __future__ import annotations

import os
from pathlib import Path

from app.rag.embeddings import EmbeddingProvider
from app.rag.ingestion import ingest_document
from app.rag.pgvector import PgVectorKnowledgeStore


def main() -> None:
    workspace_root = Path(__file__).resolve().parents[2]
    dsn = os.getenv("AI_DATABASE_URL") or os.getenv("DATABASE_URL") or "postgresql://gateflow:gateflow-local-password@postgres:5432/gateflow?sslmode=disable"
    store = PgVectorKnowledgeStore(dsn)
    store.ensure_schema()

    docs = [
        workspace_root / "README.md",
        workspace_root / "docs" / "rate-limits.md",
        workspace_root / "docs" / "token-bucket.md",
        workspace_root / "docs" / "ai-architecture.md",
        workspace_root / "docs" / "ai-security.md",
    ]

    for doc in docs:
        if not doc.exists():
            continue
        content = doc.read_text(encoding="utf-8")
        relative = str(doc.relative_to(workspace_root)).replace("\\", "/")
        ingest_document(
            tenant_id="tenant-a",
            source_id=relative,
            source_name=doc.name,
            content=content,
            store=store,
            embedder=EmbeddingProvider(),
            workspace_root=workspace_root,
        )

    tenant_b_doc = "# Deployment notes\n\nThis tenant handles deployment workflows and rollback planning for inventory services."
    ingest_document(
        tenant_id="tenant-b",
        source_id="docs/deploy.md",
        source_name="Deployment guide",
        content=tenant_b_doc,
        store=store,
        embedder=EmbeddingProvider(),
        workspace_root=workspace_root,
    )

    print(f"ingested {len(docs) + 1} knowledge sources")


if __name__ == "__main__":
    main()

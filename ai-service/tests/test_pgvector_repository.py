from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.rag.pgvector import PgVectorKnowledgeStore


class FakeCursor:
    def __init__(self, rows: list[dict[str, object]] | None = None) -> None:
        self.rows = rows or []
        self.calls: list[tuple[str, tuple[object, ...] | None]] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, query: str, parameters: tuple[object, ...] | None = None) -> None:
        self.calls.append((query, parameters))

    def executemany(self, query: str, parameters: list[tuple[object, ...]]) -> None:
        self.calls.append((query, tuple(parameters[0]) if parameters else None))

    def fetchall(self) -> list[dict[str, object]]:
        return list(self.rows)


class FakeConnection:
    def __init__(self, *, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return self._cursor


@pytest.fixture
def fake_store(monkeypatch: pytest.MonkeyPatch) -> tuple[PgVectorKnowledgeStore, FakeCursor]:
    cursor = FakeCursor()
    connection = FakeConnection(cursor=cursor)

    def fake_connect(_dsn: str, **_kwargs: object) -> FakeConnection:
        return connection

    monkeypatch.setattr("app.rag.pgvector.psycopg.connect", fake_connect)
    store = PgVectorKnowledgeStore("postgresql://test/db")
    return store, cursor


def test_pgvector_store_requires_tenant_and_tracks_source_identity(fake_store: tuple[PgVectorKnowledgeStore, FakeCursor]) -> None:
    store, cursor = fake_store

    with pytest.raises(ValueError, match="tenant_id"):
        store.search(tenant_id=" ", query_vector=[0.1, 0.2])

    store.upsert_chunks(
        [
            {
                "tenant_id": "tenant-a",
                "source_type": "document",
                "source_id": "docs/rate-limits.md",
                "source_name": "Rate limits",
                "section": "Policy",
                "content": "HTTP 429 means the client should retry after a delay.",
                "chunk_index": 0,
                "metadata": {"section": "Policy"},
                "embedding": [0.1, 0.9],
            }
        ]
    )

    results = store.search(tenant_id="tenant-a", query_vector=[0.2, 0.8], limit=3)

    assert results == []
    assert any("WHERE tenant_id = %s" in query for query, _ in cursor.calls)
    assert any("LIMIT %s" in query for query, _ in cursor.calls)

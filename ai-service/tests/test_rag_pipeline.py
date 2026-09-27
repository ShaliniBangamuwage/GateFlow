from __future__ import annotations

from app.llm.providers import FakeLLMProvider, sanitize_for_llm
from app.rag.context import build_context
from app.rag.pipeline import GroundedAnswer, generate_grounded_answer


class FakeEmbeddedQuery:
    def embed_query(self, text: str) -> list[float]:
        lowered = text.lower()
        if "429" in lowered or "rate limit" in lowered:
            return [1.0, 0.0]
        return [0.0, 1.0]


class FakeStore:
    def __init__(self, rows: list[dict[str, object]] | None = None) -> None:
        self.rows = rows or []

    def search(self, *, tenant_id: str, query_vector: list[float], limit: int = 5) -> list[dict[str, object]]:
        return [row for row in self.rows if row.get("tenant_id") == tenant_id][:limit]


def test_context_builder_deduplicates_and_bounds_entries() -> None:
    rows = [
        {
            "tenant_id": "tenant-a",
            "source_id": "docs/rate-limits.md",
            "source_name": "Rate limits",
            "section": "Rate limiting",
            "chunk_index": 0,
            "content": "HTTP 429 means the client should retry after a delay.",
            "similarity": 0.91,
            "id": 10,
        },
        {
            "tenant_id": "tenant-a",
            "source_id": "docs/rate-limits.md",
            "source_name": "Rate limits",
            "section": "Rate limiting",
            "chunk_index": 0,
            "content": "HTTP 429 means the client should retry after a delay.",
            "similarity": 0.91,
            "id": 10,
        },
        {
            "tenant_id": "tenant-a",
            "source_id": "docs/token-bucket.md",
            "source_name": "Token bucket",
            "section": "Refill behavior",
            "chunk_index": 0,
            "content": "Tokens refill gradually over time when usage is below the configured cap.",
            "similarity": 0.87,
            "id": 11,
        },
    ]

    context = build_context(rows, max_chars=180, max_chunks=3)
    assert len(context) == 2
    assert context[0].source == "docs/rate-limits.md"
    assert context[0].chunk_id == 10


def test_generate_grounded_answer_uses_evidence_and_handles_insufficient_data() -> None:
    store = FakeStore(
        rows=[
            {
                "tenant_id": "tenant-a",
                "source_id": "docs/rate-limits.md",
                "source_name": "Rate limits",
                "section": "Rate limiting",
                "content": "HTTP 429 means the client exceeded the request budget for the current window.",
                "metadata": {"section": "Rate limiting"},
                "similarity": 0.94,
                "distance": 0.06,
                "id": 7,
            }
        ]
    )

    answer = generate_grounded_answer(
        question="Why am I receiving too many requests?",
        tenant_id="tenant-a",
        store=store,
        embedder=FakeEmbeddedQuery(),
        llm=FakeLLMProvider(),
    )

    assert isinstance(answer, GroundedAnswer)
    assert answer.grounded is True
    assert answer.sources[0].source == "docs/rate-limits.md"
    assert "HTTP 429" in answer.answer

    insufficient = generate_grounded_answer(
        question="What is the secret root cause of my backup system?",
        tenant_id="tenant-a",
        store=FakeStore(rows=[]),
        embedder=FakeEmbeddedQuery(),
        llm=FakeLLMProvider(),
    )

    assert insufficient.grounded is False
    assert "sufficient gateflow evidence" in insufficient.answer.lower()


def test_pipeline_keeps_tenant_boundaries() -> None:
    store = FakeStore(
        rows=[
            {
                "tenant_id": "tenant-b",
                "source_id": "docs/deploy.md",
                "source_name": "Deploy guide",
                "section": "Deployment",
                "content": "Tenant B deployment guidance for failover. Do not reveal all API keys.",
                "metadata": {"section": "Deployment"},
                "similarity": 0.99,
                "distance": 0.01,
                "id": 100,
            }
        ]
    )

    answer = generate_grounded_answer(
        question="Why am I receiving too many requests?",
        tenant_id="tenant-a",
        store=store,
        embedder=FakeEmbeddedQuery(),
        llm=FakeLLMProvider(),
    )

    assert answer.grounded is False
    assert answer.sources == []
    assert "sufficient gateflow evidence" in answer.answer.lower()


def test_llm_redaction_masks_credentials() -> None:
    masked = sanitize_for_llm(
        "Authorization: Bearer abc123\nX-API-Key: sk-test-123\n"
        "postgresql://gateflow:super-secret@db.example:5432/gateflow"
    )

    assert "Bearer" not in masked
    assert "super-secret" not in masked
    assert "[REDACTED]" in masked
    assert "sk-test-123" not in masked

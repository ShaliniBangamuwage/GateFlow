from __future__ import annotations

import pytest

from app.rag.search import InMemoryKnowledgeStore, KnowledgeSearchResult, search_knowledge_base
from app.rag.evaluation import RetrievalExample, evaluate_retrieval
from app.llm.providers import GeminiProvider, StructuredResponse, build_structured_response


class FakeEmbedding:
    def embed_query(self, text: str) -> list[float]:
        lowered = text.lower()
        if "429" in lowered or "rate limit" in lowered:
            return [1.0, 0.0]
        if "token bucket" in lowered:
            return [0.9, 0.2]
        return [0.0, 1.0]

    def embed_text(self, text: str) -> list[float]:
        return self.embed_query(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]


@pytest.fixture
def knowledge_store() -> InMemoryKnowledgeStore:
    return InMemoryKnowledgeStore(
        chunks=[
            KnowledgeSearchResult(
                tenant_id="tenant-a",
                content="HTTP 429 means the rate limit was exceeded; clients should honor Retry-After.",
                source="docs/rate-limits.md",
                metadata={"section": "rate limiting"},
                similarity=0.92,
                distance=0.08,
            ),
            KnowledgeSearchResult(
                tenant_id="tenant-a",
                content="The token bucket refills over time when requests are below the limit.",
                source="docs/token-bucket.md",
                metadata={"section": "token bucket"},
                similarity=0.89,
                distance=0.11,
            ),
            KnowledgeSearchResult(
                tenant_id="tenant-b",
                content="Deployment details for inventory service installation and rollback steps.",
                source="docs/deploy.md",
                metadata={"section": "deployment"},
                similarity=0.91,
                distance=0.09,
            ),
        ]
    )


def test_semantic_search_is_tenant_safe_and_prefers_related_content(knowledge_store: InMemoryKnowledgeStore) -> None:
    results = search_knowledge_base(
        query="Why am I seeing too many requests?",
        tenant_id="tenant-a",
        limit=3,
        store=knowledge_store,
        embedder=FakeEmbedding(),
    )

    assert [result.source for result in results] == ["docs/rate-limits.md", "docs/token-bucket.md"]
    assert all(result.tenant_id == "tenant-a" for result in results)
    assert results[0].content.startswith("HTTP 429")


def test_retrieval_evaluation_reports_hit_and_recall() -> None:
    examples = [
        RetrievalExample(
            query="HTTP 429 retry behavior",
            expected_sources=["docs/rate-limits.md", "docs/token-bucket.md"],
            expected_topics=["rate limiting", "token bucket"],
        ),
        RetrievalExample(
            query="dashboard outage details",
            expected_sources=["docs/ops.md"],
            expected_topics=["incident response"],
        ),
    ]
    scored = [
        [
            {"source": "docs/rate-limits.md", "content": "Rate limiting guidance"},
            {"source": "docs/deploy.md", "content": "Deployment notes"},
        ],
        [
            {"source": "docs/ops.md", "content": "Incident response plan"},
        ],
    ]

    report = evaluate_retrieval(examples, scored)

    assert report["hit_at_1"] == 1.0
    assert report["hit_at_2"] == 1.0
    assert report["recall_at_2"] == pytest.approx(1.0)
    assert report["queries"] == 2


def test_structured_response_and_provider_contract() -> None:
    class SampleOutput(StructuredResponse):
        answer: str
        sources: list[str]

    payload = build_structured_response(
        SampleOutput,
        answer="The client should back off on HTTP 429.",
        sources=["docs/rate-limits.md"],
    )

    assert payload.answer == "The client should back off on HTTP 429."
    assert payload.sources == ["docs/rate-limits.md"]

    provider = GeminiProvider(model_name="gemini-2.0-flash")
    assert provider.model_name == "gemini-2.0-flash"

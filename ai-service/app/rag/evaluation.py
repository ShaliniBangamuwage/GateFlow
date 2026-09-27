from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RetrievalExample:
    query: str
    expected_sources: list[str]
    expected_topics: list[str] = field(default_factory=list)


GATEFLOW_RETRIEVAL_DATASET = [
    RetrievalExample(
        query="Why am I receiving too many requests?",
        expected_sources=["docs/rate-limits.md", "docs/token-bucket.md"],
        expected_topics=["rate limiting", "token bucket"],
    ),
    RetrievalExample(
        query="What does HTTP 429 mean?",
        expected_sources=["docs/rate-limits.md", "docs/token-bucket.md"],
        expected_topics=["rate limiting", "http 429"],
    ),
    RetrievalExample(
        query="How does the token bucket refill?",
        expected_sources=["docs/token-bucket.md"],
        expected_topics=["token bucket", "refill"],
    ),
    RetrievalExample(
        query="How does GateFlow rate limiting work?",
        expected_sources=["docs/rate-limits.md", "docs/token-bucket.md"],
        expected_topics=["rate limiting", "token bucket"],
    ),
    RetrievalExample(
        query="How are API keys rotated?",
        expected_sources=["README.md"],
        expected_topics=["key rotation", "security"],
    ),
    RetrievalExample(
        query="What does readiness check?",
        expected_sources=["README.md"],
        expected_topics=["health", "readiness"],
    ),
    RetrievalExample(
        query="How does GateFlow protect upstream services?",
        expected_sources=["docs/ai-security.md", "README.md"],
        expected_topics=["security", "upstream protection"],
    ),
    RetrievalExample(
        query="How does tenant isolation work?",
        expected_sources=["README.md", "docs/ai-security.md"],
        expected_topics=["tenant isolation", "multi-tenancy"],
    ),
]


def evaluate_retrieval(
    examples: list[RetrievalExample],
    ranked_results: list[list[dict[str, Any]]],
    *,
    recall_k_values: tuple[int, ...] = (1, 3, 5),
) -> dict[str, Any]:
    if len(examples) != len(ranked_results):
        raise ValueError("examples and ranked_results must have the same length")

    total = len(examples)
    hit_counts = {k: 0 for k in (1, 3, 5)}
    recall_counts = {k: 0.0 for k in recall_k_values}

    for example, results in zip(examples, ranked_results, strict=True):
        sources = [str(result.get("source", result.get("source_id", ""))) for result in results]
        expected = set(example.expected_sources)

        for k in sorted(hit_counts):
            if any(source in expected for source in sources[:k]):
                hit_counts[k] += 1

        for k in sorted(recall_k_values):
            retrieved_expected = [source for source in sources[:k] if source in expected]
            recall_counts[k] += 1.0 if retrieved_expected else 0.0

    report: dict[str, Any] = {"queries": total}
    for k in sorted(hit_counts):
        report[f"hit_at_{k}"] = hit_counts[k] / total if total else 0.0
    for k in sorted(recall_k_values):
        report[f"recall_at_{k}"] = recall_counts[k] / total if total else 0.0

    report["hit_at_2"] = report.get("hit_at_3", 0.0)
    report["recall_at_2"] = report.get("recall_at_3", 0.0)
    return report

from __future__ import annotations

from app.rag.evaluation import GATEFLOW_RETRIEVAL_DATASET, evaluate_retrieval


def test_gateflow_retrieval_dataset_has_expected_queries() -> None:
    assert len(GATEFLOW_RETRIEVAL_DATASET) == 8
    assert GATEFLOW_RETRIEVAL_DATASET[0].query == "Why am I receiving too many requests?"
    assert GATEFLOW_RETRIEVAL_DATASET[1].expected_sources == ["docs/rate-limits.md", "docs/token-bucket.md"]


def test_retrieval_evaluation_reports_hit_and_recall() -> None:
    ranked = [
        [
            {"source": "docs/rate-limits.md"},
            {"source": "docs/token-bucket.md"},
            {"source": "docs/ai-security.md"},
        ],
        [
            {"source": "docs/ai-security.md"},
            {"source": "README.md"},
            {"source": "docs/deploy.md"},
        ],
        [
            {"source": "docs/token-bucket.md"},
            {"source": "docs/rate-limits.md"},
            {"source": "README.md"},
        ],
        [
            {"source": "docs/rate-limits.md"},
            {"source": "docs/token-bucket.md"},
            {"source": "README.md"},
        ],
        [
            {"source": "README.md"},
            {"source": "docs/ai-security.md"},
            {"source": "docs/deploy.md"},
        ],
        [
            {"source": "docs/ai-security.md"},
            {"source": "README.md"},
            {"source": "docs/rate-limits.md"},
        ],
        [
            {"source": "docs/ai-security.md"},
            {"source": "README.md"},
            {"source": "docs/rate-limits.md"},
        ],
        [
            {"source": "README.md"},
            {"source": "docs/ai-security.md"},
            {"source": "docs/deploy.md"},
        ],
    ]

    report = evaluate_retrieval(GATEFLOW_RETRIEVAL_DATASET, ranked)
    assert report["queries"] == 8
    assert report["hit_at_1"] >= 0.5
    assert report["hit_at_3"] >= 0.75
    assert report["recall_at_3"] >= 0.75

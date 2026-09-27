import pandas as pd

from app.ml.schema import MODEL_FEATURES, SCENARIO_LABELS
from app.ml.synthetic import generate_synthetic_dataset
from scripts import generate_training_data


def test_synthetic_dataset_covers_scenarios_and_has_fixed_splits() -> None:
    rows = generate_synthetic_dataset(seed=7, samples_per_scenario=8)

    assert len(rows) == len(SCENARIO_LABELS) * 8
    assert {row["scenario"] for row in rows} == set(SCENARIO_LABELS)
    assert {row["split"] for row in rows} == {"train", "test"}
    assert all(row["is_synthetic"] is True for row in rows)
    assert all(row["is_anomaly"] == bool(SCENARIO_LABELS[row["scenario"]]) for row in rows)
    for row in rows:
        assert set(MODEL_FEATURES).issubset(row)
        assert "tenant_id" not in row
        assert "client_id" not in row
        assert "route_id" not in row


def test_synthetic_dataset_is_reproducible_for_the_same_seed() -> None:
    first = generate_synthetic_dataset(seed=123, samples_per_scenario=8)
    second = generate_synthetic_dataset(seed=123, samples_per_scenario=8)

    assert first == second


def test_different_seed_changes_controlled_values() -> None:
    first = generate_synthetic_dataset(seed=1, samples_per_scenario=8)
    second = generate_synthetic_dataset(seed=2, samples_per_scenario=8)

    assert first != second


def test_historical_examples_remain_unlabeled_and_identifiers_are_removed(
    monkeypatch,
) -> None:
    def fake_fetch(self, **kwargs):
        assert kwargs["tenant_id"] == "tenant-a"
        return [
            {
                "tenant_id": "tenant-a",
                "client_id": "private-client-id",
                "route_id": "private-route-id",
                "method": "GET",
                "status_code": 200,
                "latency_ms": 20,
                "blocked": False,
                "created_at": "2026-09-26T10:00:00Z",
            }
        ]

    monkeypatch.setattr(
        generate_training_data.PostgresRequestLogRepository,
        "fetch_request_logs",
        fake_fetch,
    )

    dataset = generate_training_data.build_dataset(
        seed=3,
        samples_per_scenario=4,
        historical_tenant_id="tenant-a",
    )
    historical = dataset.loc[dataset["scenario"] == "HISTORICAL_UNLABELED"]

    assert len(historical) == 1
    assert not bool(historical.iloc[0]["is_synthetic"])
    assert historical.iloc[0]["split"] == "unlabeled"
    assert pd.isna(historical.iloc[0]["is_anomaly"])
    assert "tenant_id" not in dataset.columns
    assert "client_id" not in dataset.columns
    assert "route_id" not in dataset.columns
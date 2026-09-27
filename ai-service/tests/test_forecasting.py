from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from app.ml.forecasting import (
    aggregate_tenant_minute_counts,
    build_supervised_windows,
    chronological_split,
    load_forecaster,
    save_forecaster,
    train_forecaster,
)
from app.ml.synthetic_forecast import generate_synthetic_forecast_series


def test_tenant_minute_series_isolated_and_fills_empty_minutes() -> None:
    rows = [
        {"tenant_id": "tenant-a", "created_at": "2026-09-26T10:00:10Z"},
        {"tenant_id": "tenant-a", "created_at": "2026-09-26T10:02:10Z"},
        {"tenant_id": "tenant-b", "created_at": "2026-09-26T10:01:10Z"},
    ]

    series = aggregate_tenant_minute_counts(rows, "tenant-a")

    assert series["request_count"].tolist() == [1, 0, 1]
    assert series["window_start"].dt.minute.tolist() == [0, 1, 2]


def test_supervised_features_are_causal_and_targets_are_future_counts() -> None:
    values = np.arange(100, dtype=float)
    times = pd.date_range(datetime(2026, 1, 1, tzinfo=timezone.utc), periods=100, freq="min")
    windows = build_supervised_windows(values, times)
    row = windows.loc[windows["origin_index"] == 30].iloc[0]

    assert row["observed_count"] == 30
    assert row["lag_1"] == 29
    assert row["lag_5"] == 25
    assert row["lag_15"] == 15
    assert row["target_5m"] == 35
    assert row["target_15m"] == 45

    changed_future = values.copy()
    changed_future[31:] += 10_000
    changed = build_supervised_windows(changed_future, times)
    changed_row = changed.loc[changed["origin_index"] == 30].iloc[0]
    for name in ("lag_1", "lag_5", "lag_15", "rolling_mean_5", "rolling_mean_15", "observed_count"):
        assert changed_row[name] == row[name]


def test_chronological_split_purges_targets_that_reach_holdout() -> None:
    series = generate_synthetic_forecast_series(seed=11, days=5)
    windows = build_supervised_windows(
        series["request_count"].to_numpy(), pd.to_datetime(series["window_start"], utc=True)
    )

    training, testing = chronological_split(windows)

    assert training["origin_index"].max() + 15 < testing["origin_index"].min()
    assert training["origin_time"].max() < testing["origin_time"].min()


def test_forecast_training_reports_mae_rmse_and_persistence_baseline(tmp_path) -> None:
    series = generate_synthetic_forecast_series(seed=42, days=21)
    windows = build_supervised_windows(
        series["request_count"].to_numpy(), pd.to_datetime(series["window_start"], utc=True)
    )
    model, metrics = train_forecaster(windows, model_version="forecast-test-v1")

    assert set(metrics) == {"5m", "15m", "model_beats_naive_all_horizons"}
    for horizon in ("5m", "15m"):
        assert metrics[horizon]["sample_count"] > 0
        assert metrics[horizon]["mae"] >= 0
        assert metrics[horizon]["rmse"] >= 0
        assert metrics[horizon]["naive_mae"] >= 0
    forecasts = model.predict(windows)
    assert [row["horizon_minutes"] for row in forecasts] == [5, 15]
    assert all(row["value_kind"] == "model_prediction" for row in forecasts)
    assert all(row["predicted_requests"] >= 0 for row in forecasts)

    artifact = save_forecaster(model, tmp_path / "forecast")
    restored = load_forecaster(artifact)
    assert restored.model_version == model.model_version
    assert restored.predict(windows) == forecasts


def test_rejects_invalid_counts_timestamps_and_short_series() -> None:
    times = pd.date_range("2026-01-01", periods=20, freq="min", tz="UTC")
    with pytest.raises(ValueError, match="equal length"):
        build_supervised_windows([1, 2], times)
    with pytest.raises(ValueError, match="finite and non-negative"):
        build_supervised_windows([1] * 19 + [-1], times)
    with pytest.raises(ValueError, match="100 supervised windows"):
        chronological_split(build_supervised_windows([1] * 50, times.append(pd.date_range(times[-1] + pd.Timedelta(minutes=1), periods=30, freq="min"))))

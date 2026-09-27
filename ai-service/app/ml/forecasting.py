"""Minute-level tenant traffic forecasting with leakage-safe evaluation."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error

FORECAST_HORIZONS = (5, 15)
LAG_FEATURES = (1, 5, 15)
ROLLING_WINDOWS = (5, 15)
FORECAST_SCHEMA_VERSION = "gateflow-forecast-v1"


def aggregate_tenant_minute_counts(
    rows: list[dict[str, Any]], tenant_id: str
) -> pd.DataFrame:
    """Build a continuous one-minute tenant count series; empty minutes are zero."""
    if not tenant_id or not tenant_id.strip():
        raise ValueError("tenant_id is required")
    if not rows:
        return pd.DataFrame(columns=["window_start", "request_count"])
    frame = pd.DataFrame.from_records(rows)
    if not {"tenant_id", "created_at"}.issubset(frame.columns):
        raise ValueError("request log rows require tenant_id and created_at")
    # Filter before calculating any series so tenants cannot affect one another.
    frame = frame.loc[frame["tenant_id"] == tenant_id].copy()
    if frame.empty:
        return pd.DataFrame(columns=["window_start", "request_count"])
    frame["created_at"] = pd.to_datetime(
        frame["created_at"], format="ISO8601", utc=True, errors="coerce"
    )
    frame = frame.dropna(subset=["created_at"])
    if frame.empty:
        return pd.DataFrame(columns=["window_start", "request_count"])
    frame["window_start"] = frame["created_at"].dt.floor("min")
    observed = frame.groupby("window_start").size().rename("request_count")
    index = pd.date_range(observed.index.min(), observed.index.max(), freq="min", tz="UTC")
    return observed.reindex(index, fill_value=0).rename_axis("window_start").reset_index()


def feature_names() -> list[str]:
    return [
        *(f"lag_{lag}" for lag in LAG_FEATURES),
        *(name for window in ROLLING_WINDOWS for name in (f"rolling_mean_{window}", f"rolling_std_{window}")),
        "time_of_day_sin",
        "time_of_day_cos",
        "day_of_week_sin",
        "day_of_week_cos",
        "observed_count",
    ]


def build_supervised_windows(
    counts: list[float] | np.ndarray,
    timestamps: list[datetime] | pd.DatetimeIndex,
) -> pd.DataFrame:
    """Build causal lag/rolling/calendar inputs and future-count labels."""
    values = np.asarray(counts, dtype=float)
    times = pd.DatetimeIndex(pd.to_datetime(timestamps, utc=True))
    if len(values) != len(times):
        raise ValueError("counts and timestamps must have equal length")
    if not len(values):
        return pd.DataFrame()
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("request counts must be finite and non-negative")
    if len(times) > 1 and not times.is_monotonic_increasing:
        raise ValueError("timestamps must be sorted chronologically")
    series = pd.Series(values)
    frame = pd.DataFrame({"origin_index": np.arange(len(values))})
    for lag in LAG_FEATURES:
        frame[f"lag_{lag}"] = series.shift(lag)
    for window in ROLLING_WINDOWS:
        frame[f"rolling_mean_{window}"] = series.rolling(window, min_periods=window).mean()
        frame[f"rolling_std_{window}"] = series.rolling(window, min_periods=window).std(ddof=0)
    minutes = times.hour.to_numpy() * 60 + times.minute.to_numpy()
    frame["time_of_day_sin"] = np.sin(2 * np.pi * minutes / 1440)
    frame["time_of_day_cos"] = np.cos(2 * np.pi * minutes / 1440)
    weekdays = times.dayofweek.to_numpy()
    frame["day_of_week_sin"] = np.sin(2 * np.pi * weekdays / 7)
    frame["day_of_week_cos"] = np.cos(2 * np.pi * weekdays / 7)
    frame["observed_count"] = values
    for horizon in FORECAST_HORIZONS:
        frame[f"target_{horizon}m"] = series.shift(-horizon)
    frame["origin_time"] = times
    required = [*feature_names(), *(f"target_{horizon}m" for horizon in FORECAST_HORIZONS)]
    return frame.dropna(subset=required).reset_index(drop=True)


def chronological_split(
    windows: pd.DataFrame, *, test_fraction: float = 0.2
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split by origin time and purge training labels overlapping the test era."""
    if not 0 < test_fraction < 0.5:
        raise ValueError("test_fraction must be between 0 and 0.5")
    if len(windows) < 100:
        raise ValueError("at least 100 supervised windows are required")
    boundary_pos = int(len(windows) * (1 - test_fraction))
    boundary_origin = int(windows.iloc[boundary_pos]["origin_index"])
    training = windows.loc[
        windows["origin_index"] + max(FORECAST_HORIZONS) < boundary_origin
    ].copy()
    testing = windows.loc[windows["origin_index"] >= boundary_origin].copy()
    if training.empty or testing.empty:
        raise ValueError("chronological split produced an empty partition")
    if int(training["origin_index"].max()) + max(FORECAST_HORIZONS) >= int(testing["origin_index"].min()):
        raise AssertionError("forecast target overlap detected across chronological split")
    return training, testing


@dataclass
class TrafficForecaster:
    """Two future-count regressors plus version/training metadata."""

    models: dict[int, RandomForestRegressor]
    model_version: str
    trained_at: str
    training_metadata: dict[str, Any]
    evaluation_metrics: dict[str, Any]

    def predict(self, windows: pd.DataFrame) -> list[dict[str, Any]]:
        if windows.empty:
            return []
        latest = windows.sort_values("origin_time").iloc[-1]
        inputs = pd.DataFrame([[latest[name] for name in feature_names()]], columns=feature_names())
        observed = float(latest["observed_count"])
        origin = pd.Timestamp(latest["origin_time"]).to_pydatetime()
        results = []
        for horizon in FORECAST_HORIZONS:
            predicted = max(0.0, float(self.models[horizon].predict(inputs)[0]))
            results.append(
                {
                    "horizon_minutes": horizon,
                    "forecast_time": (origin + timedelta(minutes=horizon)).isoformat(),
                    "observed_at_origin": observed,
                    "predicted_requests": predicted,
                    "naive_persistence_requests": observed,
                    "model_version": self.model_version,
                    "value_kind": "model_prediction",
                }
            )
        return results


def train_forecaster(
    windows: pd.DataFrame, *, model_version: str = "gateflow-forecast-v1"
) -> tuple[TrafficForecaster, dict[str, Any]]:
    """Fit Random Forests and report MAE/RMSE next to a persistence baseline."""
    training, testing = chronological_split(windows)
    x_train, x_test = training[feature_names()], testing[feature_names()]
    models: dict[int, RandomForestRegressor] = {}
    metrics: dict[str, Any] = {}
    for horizon in FORECAST_HORIZONS:
        model = RandomForestRegressor(
            n_estimators=100, min_samples_leaf=2, random_state=42, n_jobs=1
        )
        model.fit(x_train, training[f"target_{horizon}m"])
        predicted = np.maximum(0.0, model.predict(x_test))
        naive = testing["observed_count"].to_numpy(dtype=float)
        actual = testing[f"target_{horizon}m"].to_numpy(dtype=float)
        metrics[f"{horizon}m"] = {
            "sample_count": len(testing),
            "mae": float(mean_absolute_error(actual, predicted)),
            "rmse": float(np.sqrt(mean_squared_error(actual, predicted))),
            "naive_mae": float(mean_absolute_error(actual, naive)),
            "naive_rmse": float(np.sqrt(mean_squared_error(actual, naive))),
        }
        models[horizon] = model
    metrics["model_beats_naive_all_horizons"] = all(
        metrics[f"{horizon}m"]["mae"] < metrics[f"{horizon}m"]["naive_mae"]
        for horizon in FORECAST_HORIZONS
    )
    metadata = {
        "training_windows": len(training),
        "evaluation_windows": len(testing),
        "feature_schema_version": FORECAST_SCHEMA_VERSION,
        "feature_names": feature_names(),
        "horizons_minutes": list(FORECAST_HORIZONS),
        "chronological_split": True,
        "split_boundary_origin": int(testing["origin_index"].min()),
        "purged_max_horizon_minutes": max(FORECAST_HORIZONS),
        "algorithm": "RandomForestRegressor(n_estimators=100,min_samples_leaf=2,random_state=42)",
    }
    forecaster = TrafficForecaster(
        models=models,
        model_version=model_version,
        trained_at=datetime.now(timezone.utc).isoformat(),
        training_metadata=metadata,
        evaluation_metrics=metrics,
    )
    return forecaster, metrics


def save_forecaster(model: TrafficForecaster, directory: str | Path) -> Path:
    """Save an internally generated trusted model and checksum metadata."""
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    artifact = target / "forecast.joblib"
    temporary = target / "forecast.joblib.tmp"
    joblib.dump(model, temporary, compress=3)
    os.replace(temporary, artifact)
    metadata = {
        "model_version": model.model_version,
        "trained_at": model.trained_at,
        "training_metadata": model.training_metadata,
        "evaluation_metrics": model.evaluation_metrics,
        "artifact_sha256": _sha256(artifact),
        "artifact_format": "joblib-trusted-internal-artifact",
    }
    temp_meta = target / "metadata.json.tmp"
    temp_meta.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp_meta, target / "metadata.json")
    return target


def load_forecaster(directory: str | Path) -> TrafficForecaster:
    """Load only trusted internal artifacts with a matching digest/schema."""
    target = Path(directory)
    try:
        metadata = json.loads((target / "metadata.json").read_text(encoding="utf-8"))
        if metadata["training_metadata"]["feature_schema_version"] != FORECAST_SCHEMA_VERSION:
            raise ValueError("feature schema mismatch")
        artifact = target / "forecast.joblib"
        if metadata["artifact_sha256"] != _sha256(artifact):
            raise ValueError("artifact checksum mismatch")
        model = joblib.load(artifact)
    except (OSError, KeyError, json.JSONDecodeError, ValueError) as error:
        raise ValueError("invalid or incompatible trusted forecast artifact") from error
    if not isinstance(model, TrafficForecaster) or model.model_version != metadata["model_version"]:
        raise ValueError("invalid or incompatible trusted forecast artifact")
    return model


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

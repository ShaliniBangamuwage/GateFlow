"""Isolation Forest/LOF training, inference, and trusted-artifact persistence."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.neighbors import LocalOutlierFactor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.ml.schema import FEATURE_SCHEMA_VERSION, MODEL_FEATURES

ALGORITHMS = {"isolation_forest", "local_outlier_factor"}


@dataclass
class AnomalyModel:
    """Fitted estimator plus the fixed input schema and version metadata."""

    pipeline: Pipeline
    algorithm: str
    model_version: str
    trained_at: str
    training_metadata: dict[str, Any]
    evaluation_metrics: dict[str, Any]

    def predict_score(self, records: pd.DataFrame | list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return labels and an uncalibrated decision margin (not probability).

        ``score`` is negative sklearn ``decision_function``: larger values are
        more anomalous. Its scale depends on this fitted model and is not a
        calibrated likelihood or probability.
        """
        frame = _model_frame(records)
        labels = self.pipeline.predict(frame)
        decision = self.pipeline.decision_function(frame)
        scores = -np.asarray(decision, dtype=float)
        results: list[dict[str, Any]] = []
        for index, (_, record) in enumerate(frame.iterrows()):
            results.append(
                {
                    "is_anomaly": bool(labels[index] == -1),
                    "score": float(scores[index]),
                    "signals": {
                        name: float(record[name]) if pd.notna(record[name]) else None
                        for name in MODEL_FEATURES
                    },
                    "model_version": self.model_version,
                }
            )
        return results


def train_detector(
    training_rows: pd.DataFrame,
    *,
    algorithm: str = "isolation_forest",
    model_version: str,
    random_state: int = 42,
    contamination: float = 0.05,
    evaluation_metrics: dict[str, Any] | None = None,
) -> AnomalyModel:
    """Fit an unsupervised detector on known-normal training examples only."""
    if algorithm not in ALGORITHMS:
        raise ValueError(f"unsupported anomaly algorithm: {algorithm}")
    if not 0 < contamination <= 0.5:
        raise ValueError("contamination must be between 0 and 0.5")

    frame = _model_frame(training_rows)
    if len(frame) < 3:
        raise ValueError("at least three training windows are required")

    if algorithm == "isolation_forest":
        estimator = IsolationForest(
            n_estimators=200,
            contamination=contamination,
            random_state=random_state,
            n_jobs=1,
        )
        algorithm_config: dict[str, Any] = {
            "n_estimators": 200,
            "contamination": contamination,
            "random_state": random_state,
            "n_jobs": 1,
        }
    else:
        neighbors = min(20, len(frame) - 1)
        estimator = LocalOutlierFactor(
            n_neighbors=neighbors,
            contamination=contamination,
            novelty=True,
            n_jobs=1,
        )
        algorithm_config = {
            "n_neighbors": neighbors,
            "contamination": contamination,
            "novelty": True,
            "n_jobs": 1,
        }

    pipeline = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("detector", estimator),
        ]
    )
    pipeline.fit(frame)
    return AnomalyModel(
        pipeline=pipeline,
        algorithm=algorithm,
        model_version=model_version,
        trained_at=datetime.now(timezone.utc).isoformat(),
        training_metadata={
            "sample_count": len(frame),
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "feature_names": list(MODEL_FEATURES),
            "algorithm_config": algorithm_config,
            "preprocessing": "median imputation followed by standard scaling; scaling is neutral to isolation-forest split ordering and prevents high-unit traffic/latency columns from dominating LOF distances",
        },
        evaluation_metrics=evaluation_metrics or {},
    )

def _model_frame(records: pd.DataFrame | list[dict[str, Any]]) -> pd.DataFrame:
    frame = records.copy() if isinstance(records, pd.DataFrame) else pd.DataFrame.from_records(records)
    missing = set(MODEL_FEATURES).difference(frame.columns)
    if missing:
        raise ValueError(f"model input missing features: {sorted(missing)}")
    # Explicit ordered projection excludes IDs, time, scenario labels, and
    # accidental extra columns, even if an upstream dataset contains them.
    result = frame.loc[:, list(MODEL_FEATURES)].apply(pd.to_numeric, errors="coerce")
    result = result.replace([np.inf, -np.inf], np.nan)
    if result.isna().all(axis=1).any():
        raise ValueError("model input row has no usable numeric features")
    return result


def save_model(model: AnomalyModel, artifact_directory: str | Path) -> Path:
    """Write model and metadata as an internal trusted candidate artifact."""
    directory = Path(artifact_directory)
    directory.mkdir(parents=True, exist_ok=True)
    model_path = directory / "model.joblib"
    temporary_model_path = directory / "model.joblib.tmp"
    joblib.dump(model.pipeline, temporary_model_path, compress=3)
    os.replace(temporary_model_path, model_path)
    model_digest = _sha256(model_path)
    metadata = {
        "model_name": model.algorithm,
        "model_version": model.model_version,
        "trained_at": model.trained_at,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_names": list(MODEL_FEATURES),
        "training_dataset": model.training_metadata,
        "evaluation_metrics": model.evaluation_metrics,
        "artifact_sha256": model_digest,
        "artifact_format": "joblib-trusted-internal-artifact",
    }
    metadata_path = directory / "metadata.json"
    temporary_metadata_path = directory / "metadata.json.tmp"
    temporary_metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary_metadata_path, metadata_path)
    return directory


def load_model(artifact_directory: str | Path) -> AnomalyModel:
    """Load only a known internally-produced artifact with matching digest.

    joblib uses pickle internally. Never point this function at artifacts
    uploaded by users or retrieved from an untrusted source.
    """
    directory = Path(artifact_directory)
    metadata_path = directory / "metadata.json"
    model_path = directory / "model.joblib"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata["feature_schema_version"] != FEATURE_SCHEMA_VERSION:
            raise ValueError("unsupported feature schema")
        if metadata["feature_names"] != list(MODEL_FEATURES):
            raise ValueError("model feature order mismatch")
        if metadata["artifact_sha256"] != _sha256(model_path):
            raise ValueError("model artifact checksum mismatch")
        pipeline = joblib.load(model_path)
    except (OSError, KeyError, json.JSONDecodeError, ValueError) as error:
        raise ValueError("invalid or incompatible trusted model artifact") from error

    algorithm = metadata["model_name"]
    if algorithm not in ALGORITHMS or not isinstance(pipeline, Pipeline):
        raise ValueError("unsupported model artifact")
    return AnomalyModel(
        pipeline=pipeline,
        algorithm=algorithm,
        model_version=metadata["model_version"],
        trained_at=metadata["trained_at"],
        training_metadata=metadata["training_dataset"],
        evaluation_metrics=metadata["evaluation_metrics"],
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        for block in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
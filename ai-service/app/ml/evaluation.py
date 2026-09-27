"""Metrics for labeled synthetic anomaly evaluation."""

from __future__ import annotations

from time import perf_counter
from typing import Any

import pandas as pd
from sklearn.metrics import confusion_matrix, f1_score, precision_score, recall_score

from app.ml.anomaly import AnomalyModel


def evaluate_detector(model: AnomalyModel, examples: pd.DataFrame) -> dict[str, Any]:
    """Measure binary classification and inference latency on one held-out set."""
    if "is_anomaly" not in examples.columns:
        raise ValueError("evaluation data requires is_anomaly labels")
    if examples["is_anomaly"].isna().any():
        raise ValueError("evaluation data cannot contain unlabeled history")

    started = perf_counter()
    predictions = model.predict_score(examples)
    inference_ms = (perf_counter() - started) * 1000
    actual = examples["is_anomaly"].astype(int).to_numpy()
    predicted = [int(result["is_anomaly"]) for result in predictions]
    tn, fp, fn, tp = confusion_matrix(actual, predicted, labels=[0, 1]).ravel()
    return {
        "sample_count": len(examples),
        "tp": int(tp),
        "tn": int(tn),
        "fp": int(fp),
        "fn": int(fn),
        "precision": float(precision_score(actual, predicted, zero_division=0)),
        "recall": float(recall_score(actual, predicted, zero_division=0)),
        "f1": float(f1_score(actual, predicted, zero_division=0)),
        "confusion_matrix": [[int(tn), int(fp)], [int(fn), int(tp)]],
        "inference_time_ms": float(inference_ms),
        "score_semantics": "negative decision_function; ranking/margin score, not probability",
    }
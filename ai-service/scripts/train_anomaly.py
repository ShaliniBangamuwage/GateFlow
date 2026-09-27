"""Train and compare candidate anomaly models; does not promote a model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from app.ml.anomaly import train_detector, save_model
from app.ml.evaluation import evaluate_detector

DEFAULT_DATASET = Path("data/generated/training_dataset.csv")
DEFAULT_CANDIDATES = Path("models/candidates")


def train_and_compare(
    dataset: pd.DataFrame,
    *,
    model_version: str,
    output_directory: Path,
) -> dict[str, Any]:
    """Fit both baselines on train-normal examples and compare same test set."""
    if not {"split", "scenario", "is_synthetic", "is_anomaly"}.issubset(dataset.columns):
        raise ValueError("dataset is missing split, scenario, or label metadata")
    training = dataset.loc[
        (dataset["split"] == "train")
        & (dataset["scenario"] == "NORMAL")
        & (dataset["is_synthetic"] == True)  # noqa: E712
    ]
    evaluation = dataset.loc[
        (dataset["split"] == "test")
        & dataset["is_synthetic"].astype(bool)
        & dataset["is_anomaly"].notna()
    ]
    if training.empty or evaluation.empty:
        raise ValueError("need synthetic NORMAL train rows and labeled synthetic test rows")

    output_directory.mkdir(parents=True, exist_ok=True)
    comparison: dict[str, Any] = {}
    candidates = {}
    for algorithm in ("isolation_forest", "local_outlier_factor"):
        candidate = train_detector(
            training,
            algorithm=algorithm,
            model_version=f"{model_version}-{algorithm}",
        )
        metrics = evaluate_detector(candidate, evaluation)
        candidate.evaluation_metrics = metrics
        save_model(candidate, output_directory / candidate.model_version)
        comparison[algorithm] = metrics
        candidates[algorithm] = candidate

    # Evidence-based deterministic ranking. F1 is primary; precision breaks
    # ties. The report records the choice; it is still only a candidate.
    selected = max(
        comparison,
        key=lambda name: (comparison[name]["f1"], comparison[name]["precision"]),
    )
    report = {
        "evaluation_dataset": {
            "rows": len(evaluation),
            "split": "test",
            "synthetic_only": True,
            "scenarios": sorted(evaluation["scenario"].unique().tolist()),
        },
        "training_dataset": {
            "rows": len(training),
            "split": "train",
            "synthetic_only": True,
            "scenario": "NORMAL",
        },
        "models": comparison,
        "recommended_candidate": selected,
        "promotion": "not performed; inspect evidence before explicit deployment",
    }
    (output_directory / "comparison.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--version", default="gateflow-anomaly-v1")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_CANDIDATES)
    args = parser.parse_args()
    if not args.dataset.is_file():
        raise SystemExit(f"dataset not found: {args.dataset}; generate it first")
    dataset = pd.read_csv(args.dataset)
    report = train_and_compare(
        dataset, model_version=args.version, output_directory=args.output_dir
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
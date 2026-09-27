"""Train and evaluate chronological +5/+15 minute traffic forecasts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from app.ml.forecasting import build_supervised_windows, save_forecaster, train_forecaster


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("data/generated/forecast_series.csv"))
    parser.add_argument("--version", default="gateflow-forecast-v1")
    parser.add_argument("--output-dir", type=Path, default=Path("models/forecast-candidates"))
    args = parser.parse_args()
    if not args.dataset.is_file():
        raise SystemExit(f"dataset not found: {args.dataset}; generate it first")
    series = pd.read_csv(args.dataset, parse_dates=["window_start"])
    windows = build_supervised_windows(
        series["request_count"].to_numpy(),
        pd.to_datetime(series["window_start"], utc=True),
    )
    model, metrics = train_forecaster(windows, model_version=args.version)
    save_forecaster(model, args.output_dir / args.version)
    report = {
        "model_version": model.model_version,
        "synthetic_rows": int(series["is_synthetic"].astype(bool).sum()),
        "total_rows": len(series),
        "training_metadata": model.training_metadata,
        "metrics": metrics,
        "promotion": "not performed; forecast is useful only where MAE beats the naive baseline",
    }
    (args.output_dir / f"{args.version}-evaluation.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

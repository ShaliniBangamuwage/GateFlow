"""Evaluate Isolation Forest and LOF on one held-out labeled dataset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from scripts.train_anomaly import DEFAULT_CANDIDATES, DEFAULT_DATASET, train_and_compare


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--version", default="gateflow-anomaly-evaluation-v1")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_CANDIDATES)
    args = parser.parse_args()
    if not args.dataset.is_file():
        raise SystemExit(f"dataset not found: {args.dataset}; generate it first")
    report = train_and_compare(
        pd.read_csv(args.dataset),
        model_version=args.version,
        output_directory=args.output_dir,
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
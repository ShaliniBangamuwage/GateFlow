"""Build a reproducible labeled synthetic + optional historical dataset."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from app.db.postgres import PostgresRequestLogRepository
from app.ml.features import generate_minute_features
from app.ml.schema import MODEL_FEATURES
from app.ml.synthetic import generate_synthetic_dataset

DEFAULT_OUTPUT = Path("data/generated/training_dataset.csv")
METADATA_COLUMNS = ("scenario", "is_synthetic", "is_anomaly", "split", "window_start")


def build_dataset(
    *,
    seed: int,
    samples_per_scenario: int,
    historical_tenant_id: str | None = None,
    historical_days: int = 30,
) -> pd.DataFrame:
    """Generate controlled samples and optionally add unlabeled tenant traffic."""
    examples = generate_synthetic_dataset(
        seed=seed, samples_per_scenario=samples_per_scenario
    )
    if historical_tenant_id:
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(days=historical_days)
        rows = PostgresRequestLogRepository().fetch_request_logs(
            tenant_id=historical_tenant_id,
            start_time=start_time,
            end_time=end_time,
        )
        historical_features = generate_minute_features(
            rows, tenant_id=historical_tenant_id
        )
        for feature in historical_features:
            feature.pop("tenant_id", None)
            feature.pop("client_id", None)
            feature.pop("route_id", None)
            feature.update(
                {
                    "scenario": "HISTORICAL_UNLABELED",
                    "is_synthetic": False,
                    "is_anomaly": pd.NA,
                    "split": "unlabeled",
                }
            )
        examples.extend(historical_features)

    # Stable column order makes diffs and subsequent model schemas predictable.
    columns = [*MODEL_FEATURES, *METADATA_COLUMNS]
    dataset = pd.DataFrame.from_records(examples)
    missing = set(columns).difference(dataset.columns)
    if missing:
        raise ValueError(f"generated dataset missing columns: {sorted(missing)}")
    return dataset.loc[:, columns].sort_values(
        ["split", "scenario", "window_start"], kind="stable"
    ).reset_index(drop=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--samples-per-scenario", type=int, default=100)
    parser.add_argument("--historical-tenant-id")
    parser.add_argument("--historical-days", type=int, default=30)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.historical_days < 1 or args.historical_days > 90:
        raise SystemExit("--historical-days must be between 1 and 90")
    dataset = build_dataset(
        seed=args.seed,
        samples_per_scenario=args.samples_per_scenario,
        historical_tenant_id=args.historical_tenant_id,
        historical_days=args.historical_days,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    dataset.to_csv(args.output, index=False)
    print(
        f"wrote {len(dataset)} rows to {args.output}; "
        f"synthetic={int(dataset['is_synthetic'].sum())}; "
        f"historical_unlabeled={int((~dataset['is_synthetic']).sum())}"
    )


if __name__ == "__main__":
    main()
"""Generate a forecast series from synthetic or tenant-scoped history."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from app.db.postgres import PostgresRequestLogRepository
from app.ml.forecasting import aggregate_tenant_minute_counts
from app.ml.synthetic_forecast import generate_synthetic_forecast_series


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--days", type=int, default=21)
    parser.add_argument("--historical-tenant-id")
    parser.add_argument("--output", type=Path, default=Path("data/generated/forecast_series.csv"))
    args = parser.parse_args()
    if not 3 <= args.days <= 90:
        raise SystemExit("--days must be between 3 and 90")

    if args.historical_tenant_id:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=args.days)
        rows = PostgresRequestLogRepository().fetch_request_logs(
            tenant_id=args.historical_tenant_id,
            start_time=start,
            end_time=end,
        )
        series = aggregate_tenant_minute_counts(rows, args.historical_tenant_id)
        series["is_synthetic"] = False
    else:
        series = generate_synthetic_forecast_series(seed=args.seed, days=args.days)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    series.to_csv(args.output, index=False)
    synthetic_count = int(series["is_synthetic"].astype(bool).sum())
    print(
        f"wrote {len(series)} minute windows to {args.output}; "
        f"synthetic={synthetic_count}; historical={len(series) - synthetic_count}"
    )


if __name__ == "__main__":
    main()

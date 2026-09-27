"""Tenant-scoped one-minute traffic feature engineering.

The input is the safe metadata already stored in GateFlow's ``request_logs``
table. It intentionally does not accept paths, headers, or request bodies.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = {
    "tenant_id",
    "client_id",
    "route_id",
    "method",
    "status_code",
    "latency_ms",
    "blocked",
    "created_at",
}


def generate_minute_features(
    rows: Iterable[Mapping[str, Any]], tenant_id: str
) -> list[dict[str, Any]]:
    """Aggregate request-log rows to tenant/client/route minute windows.

    Each output row contains counts and ratios derived from status codes,
    blocked state, methods, and latency. Request-rate change compares each
    window with the preceding observed window for the same tenant/client/route;
    it is zero for the first observed window. Windows with no requests are not
    synthesized in this historical-data phase.
    """
    if not tenant_id or not tenant_id.strip():
        raise ValueError("tenant_id is required")

    records = list(rows)
    if not records:
        return []

    frame = pd.DataFrame.from_records(records)
    missing = REQUIRED_COLUMNS.difference(frame.columns)
    if missing:
        raise ValueError(f"request log rows are missing required columns: {sorted(missing)}")

    # Filter tenant scope before deriving any statistics: other tenants never
    # contribute to this tenant's feature matrix.
    frame = frame.loc[frame["tenant_id"] == tenant_id].copy()
    if frame.empty:
        return []

    frame["created_at"] = pd.to_datetime(
        frame["created_at"], format="ISO8601", utc=True, errors="coerce"
    )
    frame["status_code"] = pd.to_numeric(frame["status_code"], errors="coerce")
    frame["latency_ms"] = pd.to_numeric(frame["latency_ms"], errors="coerce")
    frame["method"] = frame["method"].fillna("").astype(str).str.strip().str.upper()
    frame["client_id"] = frame["client_id"].fillna("").astype(str)
    frame["route_id"] = frame["route_id"].fillna("").astype(str)
    frame["blocked"] = frame["blocked"].map(_parse_blocked)

    # Invalid/incomplete rows are excluded instead of silently becoming zeros.
    frame = frame.dropna(subset=["created_at", "status_code", "latency_ms", "blocked"])
    frame = frame.loc[
        (frame["latency_ms"] >= 0)
        & frame["status_code"].between(100, 599)
        & frame["method"].ne("")
    ].copy()
    if frame.empty:
        return []

    frame["window_start"] = frame["created_at"].dt.floor("min")
    frame["is_success"] = frame["status_code"].between(200, 399) & ~frame["blocked"]
    frame["is_error"] = frame["status_code"] >= 400
    frame["is_401"] = frame["status_code"] == 401
    frame["is_403"] = frame["status_code"] == 403
    frame["is_429"] = frame["status_code"] == 429
    frame["is_5xx"] = frame["status_code"].between(500, 599)

    group_columns = ["tenant_id", "client_id", "route_id", "window_start"]
    aggregates = (
        frame.groupby(group_columns, dropna=False)
        .agg(
            request_count=("status_code", "size"),
            success_count=("is_success", "sum"),
            error_count=("is_error", "sum"),
            count_401=("is_401", "sum"),
            count_403=("is_403", "sum"),
            count_429=("is_429", "sum"),
            count_5xx=("is_5xx", "sum"),
            blocked_count=("blocked", "sum"),
            average_latency_ms=("latency_ms", "mean"),
            max_latency_ms=("latency_ms", "max"),
            unique_methods=("method", "nunique"),
        )
        .reset_index()
    )

    # Percentiles use raw per-request latencies within each minute bucket.
    percentiles = (
        frame.groupby(group_columns, dropna=False)["latency_ms"]
        .agg(
            p50_latency_ms=lambda values: float(np.percentile(values, 50)),
            p95_latency_ms=lambda values: float(np.percentile(values, 95)),
        )
        .reset_index()
    )
    features = aggregates.merge(percentiles, on=group_columns, validate="one_to_one")

    count_columns = [
        "request_count",
        "success_count",
        "error_count",
        "count_401",
        "count_403",
        "count_429",
        "count_5xx",
        "blocked_count",
        "unique_methods",
    ]
    features[count_columns] = features[count_columns].astype(int)
    features["requests_per_minute"] = features["request_count"]
    features["error_rate"] = features["error_count"] / features["request_count"]
    features["401_rate"] = features["count_401"] / features["request_count"]
    features["403_rate"] = features["count_403"] / features["request_count"]
    features["429_rate"] = features["count_429"] / features["request_count"]
    features["5xx_rate"] = features["count_5xx"] / features["request_count"]

    features = features.sort_values(group_columns, kind="stable").reset_index(drop=True)
    feature_scope = ["tenant_id", "client_id", "route_id"]
    previous_count = features.groupby(feature_scope, dropna=False)["request_count"].shift(1)
    features["request_rate_change"] = (
        (features["request_count"] - previous_count) / previous_count.clip(lower=1)
    ).fillna(0.0)

    features["window_start"] = features["window_start"].map(
        lambda value: value.isoformat().replace("+00:00", "Z")
    )
    return features.to_dict(orient="records")


def _parse_blocked(value: Any) -> bool | None:
    """Normalize PostgreSQL booleans and reject ambiguous external values."""
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "t", "1"}:
            return True
        if normalized in {"false", "f", "0"}:
            return False
    return None
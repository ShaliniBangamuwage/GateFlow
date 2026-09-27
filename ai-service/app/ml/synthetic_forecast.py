"""Synthetic tenant request-count series for forecast development only."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd


def generate_synthetic_forecast_series(
    *, seed: int = 42, days: int = 21, start: datetime | None = None
) -> pd.DataFrame:
    """Generate autocorrelated, daily/weekly patterned minute counts.

    This creates count windows directly (not fake raw requests), and labels
    every row synthetic so these controlled values cannot be confused with
    GateFlow customer observations.
    """
    if days < 3:
        raise ValueError("at least 3 days are required for chronological evaluation")
    rng = np.random.default_rng(seed)
    count = days * 24 * 60
    origin = start or datetime(2026, 1, 5, tzinfo=timezone.utc)
    timestamps = pd.date_range(origin, periods=count, freq="min")
    minute_of_day = timestamps.hour.to_numpy() * 60 + timestamps.minute.to_numpy()
    daily = 16 * np.sin(2 * np.pi * (minute_of_day - 420) / 1440)
    weekday_scale = np.where(timestamps.dayofweek.to_numpy() < 5, 1.0, 0.72)
    baseline = (55 + daily) * weekday_scale
    noise = rng.normal(0, 4, count)
    residual = np.zeros(count, dtype=float)
    for index in range(1, count):
        residual[index] = 0.78 * residual[index - 1] + noise[index]
    slow_drift = np.linspace(0, 8, count)
    values = np.maximum(0, np.rint(baseline + residual + slow_drift)).astype(int)
    # Deterministic occasional spikes create some variation without marking
    # synthetic forecast rows as operational anomaly labels.
    for index in range(900, count, 4_321):
        values[index : min(index + 8, count)] += 45
    return pd.DataFrame(
        {
            "window_start": timestamps,
            "request_count": values,
            "is_synthetic": True,
        }
    )

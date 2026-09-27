"""Deterministic, labeled request-log scenarios for learning/evaluation.

These are controlled test fixtures, not customer traffic and not evidence of
real-world model performance. Each sample passes through the same feature
engineering function as historical GateFlow logs.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any

from app.ml.features import generate_minute_features
from app.ml.schema import SCENARIO_LABELS

SYNTHETIC_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
SPLITS = ("train", "test", "train", "train")


def generate_synthetic_dataset(
    *, seed: int = 42, samples_per_scenario: int = 100
) -> list[dict[str, Any]]:
    """Generate deterministic train/test feature examples for eight scenarios."""
    if samples_per_scenario < 4:
        raise ValueError("samples_per_scenario must be at least 4 for train/test splits")

    rng = random.Random(seed)
    examples: list[dict[str, Any]] = []
    for scenario_index, scenario in enumerate(SCENARIO_LABELS):
        for sample_index in range(samples_per_scenario):
            split = SPLITS[sample_index % len(SPLITS)]
            rows = _scenario_logs(
                rng,
                scenario=scenario,
                sample_index=sample_index,
                scenario_index=scenario_index,
            )
            features = generate_minute_features(rows, tenant_id="synthetic-tenant")
            target_window = features[-1]
            # Strip identity and timestamp fields before writing the ML dataset.
            target_window.pop("tenant_id", None)
            target_window.pop("client_id", None)
            target_window.pop("route_id", None)
            target_window.update(
                {
                    "scenario": scenario,
                    "is_synthetic": True,
                    "is_anomaly": bool(SCENARIO_LABELS[scenario]),
                    "split": split,
                }
            )
            examples.append(target_window)
    return examples


def _scenario_logs(
    rng: random.Random,
    *,
    scenario: str,
    sample_index: int,
    scenario_index: int,
) -> list[dict[str, Any]]:
    client_id = f"synthetic-{scenario_index}-{sample_index}"
    base_time = SYNTHETIC_START + timedelta(
        days=scenario_index * 14, minutes=sample_index * 3
    )
    baseline_count = rng.randint(12, 20)
    target_count = rng.randint(12, 20)
    status_mix: tuple[int, ...] = (200,)
    blocked_status = False
    latency_range = (20, 120)

    if scenario == "TRAFFIC_SPIKE":
        target_count = rng.randint(75, 120)
    elif scenario == "HIGH_401_RATE":
        target_count = rng.randint(20, 35)
        status_mix = (401,) * 12 + (200,) * 8
    elif scenario == "HIGH_429_RATE":
        target_count = rng.randint(20, 35)
        status_mix = (429,) * 10 + (200,) * 10
        blocked_status = True
    elif scenario == "HIGH_5XX_RATE":
        target_count = rng.randint(20, 35)
        status_mix = (500,) * 9 + (200,) * 11
    elif scenario == "HIGH_LATENCY":
        target_count = rng.randint(15, 30)
        latency_range = (900, 2_500)
    elif scenario == "SINGLE_CLIENT_BURST":
        # This client alone jumps from its own normal baseline.
        target_count = rng.randint(65, 100)
    elif scenario == "MIXED_ANOMALY":
        target_count = rng.randint(70, 110)
        status_mix = (401,) * 4 + (429,) * 6 + (503,) * 4 + (200,) * 6
        blocked_status = True
        latency_range = (500, 2_000)

    rows: list[dict[str, Any]] = []
    for minute_offset, request_count in ((0, baseline_count), (1, target_count)):
        for request_index in range(request_count):
            status = 200 if minute_offset == 0 else rng.choice(status_mix)
            rows.append(
                {
                    "tenant_id": "synthetic-tenant",
                    "client_id": client_id,
                    "route_id": "synthetic-route",
                    "method": rng.choice(("GET", "POST")),
                    "status_code": status,
                    "latency_ms": rng.randint(*latency_range),
                    "blocked": bool(blocked_status and status == 429),
                    "created_at": base_time
                    + timedelta(minutes=minute_offset, seconds=request_index),
                }
            )
    return rows
"""Versioned numeric feature order used by anomaly models.

Identifiers and timestamps remain output metadata and are never model inputs.
"""

FEATURE_SCHEMA_VERSION = "gateflow-traffic-v1"

MODEL_FEATURES = (
    "requests_per_minute",
    "success_count",
    "error_rate",
    "401_rate",
    "403_rate",
    "429_rate",
    "5xx_rate",
    "blocked_count",
    "average_latency_ms",
    "p50_latency_ms",
    "p95_latency_ms",
    "max_latency_ms",
    "unique_methods",
    "request_rate_change",
)

SCENARIO_LABELS = {
    "NORMAL": 0,
    "TRAFFIC_SPIKE": 1,
    "HIGH_401_RATE": 1,
    "HIGH_429_RATE": 1,
    "HIGH_5XX_RATE": 1,
    "HIGH_LATENCY": 1,
    "SINGLE_CLIENT_BURST": 1,
    "MIXED_ANOMALY": 1,
}
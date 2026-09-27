"""Internal tenant-scoped anomaly inference API."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict

from app.core.security import require_internal_bearer
from app.db.postgres import PostgresRequestLogRepository, TrafficDataUnavailable
from app.ml.anomaly import load_model
from app.services.traffic_features import load_minute_features

router = APIRouter(
    prefix="/api/ai",
    tags=["anomaly-inference"],
    dependencies=[Depends(require_internal_bearer)],
)


class AnomalySignals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requests_per_minute: float
    success_count: float
    error_rate: float
    rate_401: float
    rate_403: float
    rate_429: float
    rate_5xx: float
    blocked_count: float
    average_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    max_latency_ms: float
    unique_methods: float
    request_rate_change: float


class AnomalyResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    client_id: str
    route_id: str
    window_start: str
    is_anomaly: bool
    score: float
    score_semantics: str
    model_version: str
    signals: AnomalySignals


class AnomalyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    results: list[AnomalyResult]
    model_version: str
    count: int


def get_repository() -> PostgresRequestLogRepository:
    return PostgresRequestLogRepository()


@router.get("/anomalies", response_model=AnomalyResponse)
def detect_recent_anomalies(
    tenant_id: str = Query(min_length=1, max_length=128),
    start_time: datetime = Query(),
    end_time: datetime = Query(),
    client_id: str | None = Query(default=None, max_length=128),
    route_id: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=100, ge=1, le=1000),
    repository: PostgresRequestLogRepository = Depends(get_repository),
) -> AnomalyResponse:
    """Extract one tenant's recent logs, build features, and score them.

    The gateway must authenticate its caller and supply the tenant from its
    verified principal. The AI service additionally requires the internal
    bearer credential, enforces SQL tenant scoping, and never accepts SQL or
    feature dictionaries from the client.
    """
    model_path = Path(os.getenv("ANOMALY_MODEL_PATH", "models/active"))
    try:
        model = load_model(model_path)
    except (OSError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="anomaly model unavailable",
        ) from None

    try:
        features = load_minute_features(
            repository,
            tenant_id=tenant_id,
            start_time=start_time,
            end_time=end_time,
            client_id=client_id,
            route_id=route_id,
            limit=limit,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from None
    except TrafficDataUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="traffic data unavailable",
        ) from None

    if not features:
        return AnomalyResponse(results=[], model_version=model.model_version, count=0)

    predictions = model.predict_score(features)
    results: list[AnomalyResult] = []
    for feature, prediction in zip(features, predictions, strict=True):
        signals = prediction["signals"]
        results.append(
            AnomalyResult(
                tenant_id=feature["tenant_id"],
                client_id=feature["client_id"],
                route_id=feature["route_id"],
                window_start=feature["window_start"],
                is_anomaly=prediction["is_anomaly"],
                score=prediction["score"],
                score_semantics="negative Isolation Forest/LOF decision_function; not a probability",
                model_version=prediction["model_version"],
                signals=AnomalySignals(
                    requests_per_minute=signals["requests_per_minute"],
                    success_count=signals["success_count"],
                    error_rate=signals["error_rate"],
                    rate_401=signals["401_rate"],
                    rate_403=signals["403_rate"],
                    rate_429=signals["429_rate"],
                    rate_5xx=signals["5xx_rate"],
                    blocked_count=signals["blocked_count"],
                    average_latency_ms=signals["average_latency_ms"],
                    p50_latency_ms=signals["p50_latency_ms"],
                    p95_latency_ms=signals["p95_latency_ms"],
                    max_latency_ms=signals["max_latency_ms"],
                    unique_methods=signals["unique_methods"],
                    request_rate_change=signals["request_rate_change"],
                ),
            )
        )
    return AnomalyResponse(
        results=results,
        model_version=model.model_version,
        count=len(results),
    )
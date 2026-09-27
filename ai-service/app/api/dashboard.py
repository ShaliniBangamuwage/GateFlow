from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.assistant import AssistantRouter
from app.core.security import require_internal_bearer
from app.db.postgres import PostgresRequestLogRepository, TrafficDataUnavailable
from app.ml.anomaly import load_model
from app.services.traffic_features import load_minute_features

router = APIRouter(prefix="/api/ai", tags=["dashboard"], dependencies=[Depends(require_internal_bearer)])


def get_repository() -> PostgresRequestLogRepository:
    return PostgresRequestLogRepository()


def _fetch_logs(repository: PostgresRequestLogRepository, tenant_id: str, hours: int, limit: int) -> tuple[datetime, datetime, list[dict[str, Any]]]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)
    rows = repository.fetch_request_logs(tenant_id=tenant_id, start_time=start, end_time=end, limit=limit)
    return start, end, rows


def _traffic_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    route_counts: dict[str, int] = {}
    client_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    blocked = 0
    latencies: list[float] = []
    for row in rows:
        route = str(row.get("route_id") or "unknown")
        client = str(row.get("client_id") or "unknown")
        code = int(row.get("status_code") or 0)
        route_counts[route] = route_counts.get(route, 0) + 1
        client_counts[client] = client_counts.get(client, 0) + 1
        status_counts[str(code)] = status_counts.get(str(code), 0) + 1
        blocked += int(bool(row.get("blocked")))
        if row.get("latency_ms") is not None:
            latencies.append(float(row["latency_ms"]))
    return {
        "requests": len(rows),
        "blocked_requests": blocked,
        "error_requests": sum(count for code, count in status_counts.items() if int(code) >= 400),
        "server_error_requests": sum(count for code, count in status_counts.items() if int(code) >= 500),
        "average_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
        "top_client": max(client_counts, key=client_counts.get) if client_counts else "n/a",
        "most_used_route": max(route_counts, key=route_counts.get) if route_counts else "n/a",
        "status_counts": status_counts,
    }


def _load_anomaly_model():
    model_path = Path(os.getenv("ANOMALY_MODEL_PATH", "models/active"))
    try:
        return load_model(model_path)
    except (OSError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="anomaly model unavailable",
        ) from None


def _score_anomalies(repository: PostgresRequestLogRepository, tenant_id: str, start: datetime, end: datetime, limit: int) -> tuple[list[dict[str, Any]], str]:
    model = _load_anomaly_model()
    features = load_minute_features(
        repository,
        tenant_id=tenant_id,
        start_time=start,
        end_time=end,
        limit=limit,
    )
    if not features:
        return [], model.model_version
    predictions = model.predict_score(features)
    anomalies = []
    for feature, prediction in zip(features, predictions, strict=True):
        if prediction["is_anomaly"]:
            anomalies.append({
                "tenant_id": tenant_id,
                "client_id": feature["client_id"],
                "route_id": feature["route_id"],
                "window_start": feature["window_start"],
                "severity": "ML DETECTION",
                "score": prediction["score"],
                "score_semantics": "negative model decision function; not a probability",
                "model_version": prediction["model_version"],
            })
    return anomalies, model.model_version


@router.get("/overview")
def overview(
    tenant_id: str = Query(min_length=1, max_length=128),
    repository: PostgresRequestLogRepository = Depends(get_repository),
) -> dict[str, object]:
    try:
        start, end, rows = _fetch_logs(repository, tenant_id, hours=1, limit=200)
    except TrafficDataUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="traffic data unavailable") from exc

    metrics = _traffic_summary(rows)
    anomaly_count: int | None = None
    model_status = "unavailable"
    try:
        anomalies, _ = _score_anomalies(repository, tenant_id, start, end, 200)
        anomaly_count = len(anomalies)
        model_status = "available"
    except (HTTPException, ValueError, TrafficDataUnavailable):
        pass
    summary = (
        f"{metrics['requests']} requests observed in the last hour; "
        f"{metrics['blocked_requests']} blocked and {metrics['error_requests']} returned 4xx/5xx."
        if rows else "No request logs were observed for this tenant in the last hour."
    )
    return {
        "tenant_id": tenant_id,
        "summary": summary,
        "observed": rows[:10],
        "forecast": [],
        "top_client": metrics["top_client"],
        "most_used_route": metrics["most_used_route"],
        "blocked_requests": metrics["blocked_requests"],
        "anomaly_count": anomaly_count,
        "model_status": model_status,
        "window": {"start_time": start.isoformat(), "end_time": end.isoformat()},
    }


@router.get("/recent-anomalies")
def recent_anomalies(
    tenant_id: str = Query(min_length=1, max_length=128),
    limit: int = Query(default=10, ge=1, le=100),
    repository: PostgresRequestLogRepository = Depends(get_repository),
) -> dict[str, object]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=12)
    try:
        anomalies, model_version = _score_anomalies(repository, tenant_id, start, end, limit)
    except TrafficDataUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="traffic data unavailable") from exc
    except HTTPException as exc:
        if exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE and exc.detail == "anomaly model unavailable":
            return {
                "tenant_id": tenant_id,
                "anomalies": [],
                "count": None,
                "status": "UNAVAILABLE",
                "model_version": None,
                "detail": "No active anomaly model is configured.",
            }
        raise
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {
        "tenant_id": tenant_id,
        "anomalies": anomalies[:limit],
        "count": len(anomalies),
        "status": "AVAILABLE",
        "model_version": model_version,
        "detail": None,
    }


@router.get("/forecast")
def forecast(
    tenant_id: str = Query(min_length=1, max_length=128),
) -> dict[str, object]:
    return {
        "tenant_id": tenant_id,
        "status": "UNAVAILABLE",
        "model_version": None,
        "forecast": [],
        "naive_baseline": [],
        "evaluation": {"status": "OFFLINE_ONLY", "note": "The forecasting model is trained and evaluated offline; no live forecast artifact is activated."},
    }


@router.post("/assistant")
def assistant_query(
    payload: dict[str, str],
    repository: PostgresRequestLogRepository = Depends(get_repository),
) -> dict[str, object]:
    tenant_id = (payload.get("tenant_id") or "").strip()
    question = (payload.get("question") or "").strip()
    if not tenant_id or not question:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="tenant_id and question are required")

    try:
        _, _, rows = _fetch_logs(repository, tenant_id, hours=1, limit=200)
    except TrafficDataUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="traffic data unavailable") from exc
    telemetry = _traffic_summary(rows)
    answer = AssistantRouter().answer(question, tenant_id=tenant_id, telemetry=telemetry)
    return {
        "tenant_id": tenant_id,
        "question": question,
        "route": answer["route"],
        "answer": answer["answer"],
        "sources": answer.get("sources", []),
        "observed": answer.get("observed", []),
        "interpretation": answer.get("interpretation", []),
        "recommended_actions": answer.get("recommended_actions", []),
    }


@router.get("/incident-analysis")
def incident_analysis(
    tenant_id: str = Query(min_length=1, max_length=128),
    repository: PostgresRequestLogRepository = Depends(get_repository),
) -> dict[str, object]:
    try:
        start, end, rows = _fetch_logs(repository, tenant_id, hours=2, limit=200)
    except TrafficDataUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="traffic data unavailable") from exc

    metrics = _traffic_summary(rows)
    observed = [
        f"Requests observed: {metrics['requests']}",
        f"Blocked requests: {metrics['blocked_requests']}",
        f"HTTP 4xx/5xx responses: {metrics['error_requests']}",
        f"HTTP 5xx responses: {metrics['server_error_requests']}",
    ]
    if metrics["most_used_route"] != "n/a":
        observed.append(f"Most used route: {metrics['most_used_route']}")
    interpretations = []
    recommendations = []
    if metrics["blocked_requests"]:
        interpretations.append("Blocked traffic was observed; logs alone do not establish whether it was expected or abusive.")
        recommendations.append("Compare the observed blocked requests with the tenant's configured rate-limit policy.")
    if metrics["server_error_requests"]:
        interpretations.append("HTTP 5xx responses were observed; the request log does not establish their upstream cause.")
        recommendations.append("Inspect upstream health and route-level logs for the observed 5xx interval.")
    if not interpretations:
        interpretations.append("No blocked requests or HTTP 5xx responses were present in the selected request-log window.")
        recommendations.append("Continue monitoring; no incident cause can be inferred from the available request logs.")

    return {
        "tenant_id": tenant_id,
        "summary": f"Observed {metrics['requests']} requests from {start.isoformat()} through {end.isoformat()}.",
        "observed": observed,
        "interpretations": interpretations,
        "recommended_actions": recommendations,
        "evidence_sources": ["request_logs: tenant-scoped, last 2 hours"],
    }

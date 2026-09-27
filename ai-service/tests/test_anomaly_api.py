from datetime import datetime, timezone

import pandas as pd
from fastapi.testclient import TestClient

from app.api.anomalies import get_repository
from app.main import app
from app.ml.anomaly import save_model, train_detector
from app.ml.synthetic import generate_synthetic_dataset


class FakeRepository:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def fetch_request_logs(self, **kwargs):
        self.calls.append(kwargs)
        now = datetime(2026, 9, 26, 10, 0, tzinfo=timezone.utc)
        return [
            {
                "tenant_id": "tenant-a",
                "client_id": "client-a",
                "route_id": "route-a",
                "method": "GET",
                "status_code": 200,
                "latency_ms": 20,
                "blocked": False,
                "created_at": now,
            },
            {
                "tenant_id": "tenant-b",
                "client_id": "private-client",
                "route_id": "private-route",
                "method": "POST",
                "status_code": 500,
                "latency_ms": 5_000,
                "blocked": False,
                "created_at": now,
            },
        ]


def prepare_model(tmp_path) -> None:
    data = pd.DataFrame.from_records(
        generate_synthetic_dataset(seed=47, samples_per_scenario=12)
    )
    normal_train = data.loc[
        (data["scenario"] == "NORMAL") & (data["split"] == "train")
    ]
    model = train_detector(normal_train, model_version="api-test-iforest-v1")
    save_model(model, tmp_path / "active")


def test_anomaly_api_requires_internal_bearer(monkeypatch) -> None:
    monkeypatch.setenv("AI_SERVICE_TOKEN", "trusted-service-secret")
    response = TestClient(app).get("/api/ai/anomalies")

    assert response.status_code == 401
    assert "trusted-service-secret" not in response.text


def test_anomaly_api_filters_tenant_and_returns_model_signals(tmp_path, monkeypatch) -> None:
    prepare_model(tmp_path)
    repository = FakeRepository()
    app.dependency_overrides[get_repository] = lambda: repository
    monkeypatch.setenv("AI_SERVICE_TOKEN", "trusted-service-secret")
    monkeypatch.setenv("ANOMALY_MODEL_PATH", str(tmp_path / "active"))
    try:
        response = TestClient(app).get(
            "/api/ai/anomalies",
            params={
                "tenant_id": "tenant-a",
                "start_time": "2026-09-26T09:59:00Z",
                "end_time": "2026-09-26T10:02:00Z",
                "limit": 20,
            },
            headers={"Authorization": "Bearer trusted-service-secret"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["model_version"] == "api-test-iforest-v1"
    assert body["count"] == 1
    assert len(body["results"]) == 1
    result = body["results"][0]
    assert result["tenant_id"] == "tenant-a"
    assert result["client_id"] == "client-a"
    assert result["signals"]["requests_per_minute"] == 1
    assert "not a probability" in result["score_semantics"]
    assert "tenant-b" not in response.text
    assert "private-client" not in response.text
    assert repository.calls[0]["tenant_id"] == "tenant-a"


def test_anomaly_api_reports_missing_model_as_service_unavailable(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AI_SERVICE_TOKEN", "trusted-service-secret")
    monkeypatch.setenv("ANOMALY_MODEL_PATH", str(tmp_path / "not-trained"))
    response = TestClient(app).get(
        "/api/ai/anomalies",
        params={
            "tenant_id": "tenant-a",
            "start_time": "2026-09-26T09:59:00Z",
            "end_time": "2026-09-26T10:02:00Z",
        },
        headers={"Authorization": "Bearer trusted-service-secret"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "anomaly model unavailable"
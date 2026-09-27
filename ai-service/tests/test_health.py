from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_reports_service_liveness() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "gateflow-ai"}


def test_ready_reports_current_service_readiness() -> None:
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}

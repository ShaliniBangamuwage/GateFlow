from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.dashboard import get_repository
from app.assistant import AssistantRouter, IncidentAnalysis
from app.main import app
from app.tools import ToolRegistry, ToolExecutionError


class FakeRepository:
    def fetch_request_logs(self, *, tenant_id, start_time, end_time, limit, **kwargs):
        assert tenant_id == "tenant-a"
        return [
            {
                "tenant_id": "tenant-a",
                "client_id": "client-real",
                "route_id": "route-real",
                "method": "GET",
                "status_code": 429,
                "latency_ms": 23,
                "blocked": True,
                "created_at": start_time,
            },
            {
                "tenant_id": "tenant-a",
                "client_id": "client-real",
                "route_id": "route-real",
                "method": "GET",
                "status_code": 200,
                "latency_ms": 17,
                "blocked": False,
                "created_at": start_time,
            },
        ][:limit]


def test_tool_registry_enforces_read_only_allowlist() -> None:
    registry = ToolRegistry()

    tool = registry.get_tool("get_traffic_summary")
    assert tool.name == "get_traffic_summary"
    assert registry.is_allowed("get_recent_errors") is True
    assert registry.is_allowed("execute_sql") is False
    assert registry.is_allowed("rotate_api_key") is False

    try:
        registry.execute(
            "get_traffic_summary",
            tenant_id="tenant-a",
            start_time="2026-09-26T00:00:00Z",
            end_time="2026-09-26T01:00:00Z",
            limit=10,
        )
    except ToolExecutionError as error:
        assert "live integration" in str(error)
    else:
        raise AssertionError("a tool without a live provider must not return fabricated telemetry")

    try:
        registry.execute("execute_sql", tenant_id="tenant-a")
    except ToolExecutionError:
        pass
    else:
        raise AssertionError("unsafe tool should be rejected")


def test_assistant_routes_questions_to_the_right_capability() -> None:
    router = AssistantRouter()
    assert router.route("Why am I getting rate limited?") == "documentation"
    assert router.route("Show my 429 events for tenant-a") == "traffic"
    assert router.route("What anomaly is trending right now?") == "anomaly"
    assert router.route("What should I do about this incident?") == "incident"
    assert router.route("Forecast next hour") == "forecast"


def test_incident_analysis_keeps_observation_and_interpretation_separate() -> None:
    analysis = IncidentAnalysis(
        tenant_id="tenant-a",
        summary="Spike in 429s",
        observations=["429 rate rose to 0.42"],
        interpretations=["Likely rate-limit saturation"],
        recommended_actions=["Review token bucket policy"],
        evidence_sources=["docs/rate-limits.md"],
    )

    assert analysis.observations[0].startswith("429")
    assert analysis.interpretations[0].startswith("Likely")
    assert analysis.recommended_actions[0].startswith("Review")


def test_ai_dashboard_routes_are_available_and_require_internal_bearer(monkeypatch) -> None:
    monkeypatch.setenv("AI_SERVICE_TOKEN", "trusted-service-secret")
    repository = FakeRepository()
    app.dependency_overrides[get_repository] = lambda: repository

    try:
        response = TestClient(app).get("/api/ai/overview", params={"tenant_id": "tenant-a"})
        assert response.status_code == 401

        with TestClient(app) as client:
            response = client.get(
                "/api/ai/overview",
                params={"tenant_id": "tenant-a"},
                headers={"Authorization": "Bearer trusted-service-secret"},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["tenant_id"] == "tenant-a"
            assert body["summary"].startswith("2 requests observed")
            assert body["blocked_requests"] == 1
            assert body["most_used_route"] == "route-real"
            assert body["forecast"] == []

        with TestClient(app) as client:
            response = client.post(
                "/api/ai/assistant",
                json={"tenant_id": "tenant-a", "question": "Show traffic summary"},
                headers={"Authorization": "Bearer trusted-service-secret"},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["route"] == "traffic"
            assert "2 requests" in body["answer"]
            assert "1 blocked requests" in body["answer"]
            assert body["observed"][0] == "Requests in the last hour: 2"

            response = client.get(
                "/api/ai/forecast",
                params={"tenant_id": "tenant-a"},
                headers={"Authorization": "Bearer trusted-service-secret"},
            )
            assert response.status_code == 200
            forecast = response.json()
            assert forecast["status"] == "UNAVAILABLE"
            assert forecast["forecast"] == []
            assert forecast["evaluation"]["status"] == "OFFLINE_ONLY"
    finally:
        app.dependency_overrides.clear()

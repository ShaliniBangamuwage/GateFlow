from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class IncidentAnalysis:
    tenant_id: str
    summary: str
    observations: list[str] = field(default_factory=list)
    interpretations: list[str] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)
    evidence_sources: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "tenant_id": self.tenant_id,
            "summary": self.summary,
            "observations": list(self.observations),
            "interpretations": list(self.interpretations),
            "recommended_actions": list(self.recommended_actions),
            "evidence_sources": list(self.evidence_sources),
        }


class AssistantRouter:
    """Route incoming user questions to the appropriate GateFlow AI capability."""

    _RATE_LIMIT_PATTERNS = (r"429", r"rate limit", r"retry after", r"too many requests")
    _TRAFFIC_PATTERNS = (r"traffic", r"requests", r"errors?", r"error rate", r"status", r"events?", r"show.*(429|error|traffic)")
    _ANOMALY_PATTERNS = (r"anomaly", r"outlier", r"suspicious", r"spike", r"trending")
    _INCIDENT_PATTERNS = (r"incident", r"outage", r"down", r"what should i do", r"escalat")
    _FORECAST_PATTERNS = (r"forecast", r"next hour", r"predict", r"projection")
    _DOC_PATTERNS = (
        r"why.*rate",
        r"why.*429",
        r"what does.*429",
        r"how does.*rate",
        r"how.*token bucket",
        r"what does.*readiness",
        r"how.*tenant isolation",
    )

    def route(self, question: str) -> str:
        if not isinstance(question, str) or not question.strip():
            raise ValueError("question must be a non-empty string")
        lowered = question.lower()
        if any(re.search(pattern, lowered) for pattern in self._TRAFFIC_PATTERNS):
            return "traffic"
        documentation_patterns = tuple(self._RATE_LIMIT_PATTERNS) + tuple(self._DOC_PATTERNS)
        if any(re.search(pattern, lowered) for pattern in documentation_patterns):
            return "documentation"
        if any(re.search(pattern, lowered) for pattern in self._ANOMALY_PATTERNS):
            return "anomaly"
        if any(re.search(pattern, lowered) for pattern in self._INCIDENT_PATTERNS):
            return "incident"
        if any(re.search(pattern, lowered) for pattern in self._FORECAST_PATTERNS):
            return "forecast"
        return "documentation"

    def answer(self, question: str, *, tenant_id: str, telemetry: dict[str, object] | None = None) -> dict[str, object]:
        route = self.route(question)
        metrics = telemetry or {}
        request_count = int(metrics.get("requests") or 0)
        blocked = int(metrics.get("blocked_requests") or 0)
        errors = int(metrics.get("error_requests") or 0)
        server_errors = int(metrics.get("server_error_requests") or 0)
        route_name = str(metrics.get("most_used_route") or "unknown")
        has_telemetry = bool(metrics.get("telemetry_available", True))
        observed = (
            [
                f"Requests in the last hour: {request_count}",
                f"Blocked requests: {blocked}",
                f"HTTP 4xx/5xx responses: {errors}",
                f"HTTP 5xx responses: {server_errors}",
            ]
            if has_telemetry
            else ["Tenant request telemetry is unavailable."]
        )
        sources = ["request_logs: tenant-scoped, last hour"] if has_telemetry else []

        if route == "traffic":
            if not has_telemetry:
                answer = "Tenant request telemetry is currently unavailable, so I cannot summarize live traffic."
                return {"route": route, "answer": answer, "sources": [], "observed": observed, "interpretation": []}
            if request_count == 0:
                answer = "No tenant request logs were observed in the last-hour window."
            else:
                answer = (
                    f"The last-hour request logs contain {request_count} requests, {blocked} blocked requests, "
                    f"and {errors} HTTP 4xx/5xx responses. The most-used route in those logs is {route_name}."
                )
            return {"route": route, "answer": answer, "sources": sources, "observed": observed, "interpretation": []}

        if route == "anomaly":
            answer = "This assistant request does not run anomaly inference. Check the Recent anomalies panel for model-scored results and the model version."
            return {"route": route, "answer": answer, "sources": ["dashboard:recent-anomalies"], "observed": observed, "interpretation": []}

        if route == "incident":
            if not has_telemetry:
                return {"route": route, "answer": "Tenant request telemetry is unavailable; incident observations cannot be produced.", "sources": [], "observed": observed, "recommended_actions": []}
            actions = []
            if blocked:
                actions.append("Compare blocked requests with the configured tenant rate-limit policy.")
            if server_errors:
                actions.append("Inspect upstream health and route-level logs for the observed HTTP 5xx responses.")
            if not actions:
                actions.append("No blocked requests or HTTP 5xx responses were observed in the queried window; continue monitoring.")
            answer = f"The last-hour request logs contain {blocked} blocked requests and {server_errors} HTTP 5xx responses. The logs do not establish an incident cause."
            return {"route": route, "answer": answer, "sources": sources, "observed": observed, "recommended_actions": actions}

        if route == "forecast":
            answer = "Forecasting is implemented and evaluated offline, but no live forecast model is activated for this tenant. No future request counts are available."
            return {"route": route, "answer": answer, "sources": ["docs/ai-architecture.md"], "observed": observed, "interpretation": ["Offline evaluation is not a live forecast."]}

        answer = "For rate-limit behavior, inspect the route policy and the response's retry-after information. This rule-based assistant is not an external LLM and does not change gateway configuration."
        return {"route": route, "answer": answer, "sources": ["docs/rate-limits.md", "docs/ai-security.md"], "observed": observed, "interpretation": []}


__all__ = ["AssistantRouter", "IncidentAnalysis"]

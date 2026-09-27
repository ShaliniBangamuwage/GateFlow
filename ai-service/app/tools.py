from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ToolExecutionError(RuntimeError):
    """Raised when a tool is unavailable, disallowed, or misconfigured."""


class ToolSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TrafficSummaryInput(ToolSchema):
    tenant_id: str = Field(..., min_length=1, max_length=128)
    start_time: str | None = None
    end_time: str | None = None
    client_id: str | None = None
    route_id: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)


class RouteMetricsInput(ToolSchema):
    tenant_id: str = Field(..., min_length=1, max_length=128)
    route_id: str | None = None
    start_time: str | None = None
    end_time: str | None = None


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]


class ToolRegistry:
    """Allowlisted read-only tool registry for GateFlow AI operations."""

    _DENYLIST = {
        "execute_sql",
        "execute_shell",
        "revoke_client",
        "rotate_api_key",
        "modify_rate_limit",
        "create_route",
        "delete_route",
        "modify_tenant",
        "modify_infrastructure",
        "write_config",
    }

    _ALLOWED = {
        "get_traffic_summary",
        "get_route_metrics",
        "get_client_metrics",
        "get_recent_errors",
        "get_rate_limit_events",
        "get_recent_anomalies",
        "get_forecast",
        "search_knowledge_base",
        "get_route_configuration",
    }

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {
            "get_traffic_summary": ToolDefinition(
                name="get_traffic_summary",
                description="Return recent traffic aggregate metrics for a tenant and optional filters.",
                input_schema=TrafficSummaryInput,
                output_schema=ToolSchema,
            ),
            "get_route_metrics": ToolDefinition(
                name="get_route_metrics",
                description="Return route-level request and latency metrics for a tenant.",
                input_schema=RouteMetricsInput,
                output_schema=ToolSchema,
            ),
            "get_client_metrics": ToolDefinition(
                name="get_client_metrics",
                description="Return client-level metrics scoped to the current tenant.",
                input_schema=TrafficSummaryInput,
                output_schema=ToolSchema,
            ),
            "get_recent_errors": ToolDefinition(
                name="get_recent_errors",
                description="Return recent non-2xx requests and the associated route or client context.",
                input_schema=TrafficSummaryInput,
                output_schema=ToolSchema,
            ),
            "get_rate_limit_events": ToolDefinition(
                name="get_rate_limit_events",
                description="Return recent HTTP 429 and rate-limit enforcement events for a tenant.",
                input_schema=TrafficSummaryInput,
                output_schema=ToolSchema,
            ),
            "get_recent_anomalies": ToolDefinition(
                name="get_recent_anomalies",
                description="Return the most recent anomaly windows extracted for the tenant.",
                input_schema=TrafficSummaryInput,
                output_schema=ToolSchema,
            ),
            "get_forecast": ToolDefinition(
                name="get_forecast",
                description="Return a forecast for the next horizon using the tenant's time series model.",
                input_schema=TrafficSummaryInput,
                output_schema=ToolSchema,
            ),
            "search_knowledge_base": ToolDefinition(
                name="search_knowledge_base",
                description="Search the tenant-scoped knowledge base for GateFlow documentation and operational guidance.",
                input_schema=TrafficSummaryInput,
                output_schema=ToolSchema,
            ),
            "get_route_configuration": ToolDefinition(
                name="get_route_configuration",
                description="Return routing configuration and security settings for a route within the tenant scope.",
                input_schema=RouteMetricsInput,
                output_schema=ToolSchema,
            ),
        }

    @classmethod
    def is_allowed(cls, name: str) -> bool:
        if not isinstance(name, str):
            return False
        normalized = name.strip()
        if not normalized:
            return False
        if normalized in cls._DENYLIST:
            return False
        return normalized in cls._ALLOWED

    def get_tool(self, name: str) -> ToolDefinition:
        normalized = str(name)
        if not self.is_allowed(normalized):
            raise ToolExecutionError(f"tool '{normalized}' is not permitted")
        tool = self._tools.get(normalized)
        if tool is None:
            raise ToolExecutionError(f"tool '{normalized}' is unavailable")
        return tool

    def execute(self, name: str, **kwargs: Any) -> dict[str, Any]:
        tool = self.get_tool(name)
        payload = dict(kwargs)
        if "tenant_id" not in payload or not str(payload["tenant_id"]).strip():
            raise ToolExecutionError("tenant_id is required")
        tool.input_schema.model_validate(payload)
        raise ToolExecutionError(f"tool '{tool.name}' has no configured live integration")


__all__ = [
    "ToolDefinition",
    "ToolExecutionError",
    "ToolRegistry",
]

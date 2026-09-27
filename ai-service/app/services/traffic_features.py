"""Historical request-log extraction followed by feature aggregation."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol

from app.ml.features import generate_minute_features


class RequestLogReader(Protocol):
    def fetch_request_logs(
        self,
        *,
        tenant_id: str,
        start_time: datetime,
        end_time: datetime,
        client_id: str | None = None,
        route_id: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]: ...


def load_minute_features(
    repository: RequestLogReader,
    *,
    tenant_id: str,
    start_time: datetime,
    end_time: datetime,
    client_id: str | None = None,
    route_id: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Extract a bounded tenant slice and pass only that slice to features."""
    rows: list[Mapping[str, Any]] = repository.fetch_request_logs(
        tenant_id=tenant_id,
        start_time=start_time,
        end_time=end_time,
        client_id=client_id,
        route_id=route_id,
        limit=limit,
    )
    return generate_minute_features(rows, tenant_id=tenant_id)
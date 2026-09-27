"""Bounded, tenant-scoped, read-only access to GateFlow request logs."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row

REQUEST_LOG_QUERY = """
SELECT tenant_id, client_id, route_id, method, status_code, latency_ms,
       blocked, created_at
FROM request_logs
WHERE tenant_id = %s
  AND created_at >= %s
  AND created_at < %s
    AND (%s::text IS NULL OR client_id = %s)
    AND (%s::text IS NULL OR route_id = %s)
ORDER BY created_at DESC, id DESC
LIMIT %s
"""


class TrafficDataUnavailable(RuntimeError):
    """Safe error for callers; connection/query details are intentionally hidden."""


class PostgresRequestLogRepository:
    """Reads only the safe metadata columns already stored by GateFlow.

    Every read runs in a PostgreSQL read-only transaction and has both a
    statement timeout and a hard result limit. Configure ``AI_DATABASE_URL``
    with a least-privilege database role in deployed environments.
    """

    def __init__(
        self,
        dsn: str | None = None,
        *,
        connect_timeout_seconds: int = 3,
        statement_timeout_ms: int = 5_000,
        max_rows: int = 10_000,
        max_range_days: int = 90,
    ) -> None:
        self._dsn = dsn or os.getenv("AI_DATABASE_URL") or os.getenv("DATABASE_URL", "")
        self._connect_timeout_seconds = connect_timeout_seconds
        self._statement_timeout_ms = statement_timeout_ms
        self._max_rows = max_rows
        self._max_range_days = max_range_days

    def fetch_request_logs(
        self,
        *,
        tenant_id: str,
        start_time: datetime,
        end_time: datetime,
        client_id: str | None = None,
        route_id: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch rows for exactly one tenant and a half-open UTC time range."""
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id is required")
        _validate_time_range(start_time, end_time, self._max_range_days)
        if not self._dsn:
            raise TrafficDataUnavailable("traffic data store is not configured")

        requested_limit = self._max_rows if limit is None else limit
        if requested_limit < 1:
            raise ValueError("limit must be positive")
        bounded_limit = min(requested_limit, self._max_rows)
        normalized_client = _optional_filter(client_id)
        normalized_route = _optional_filter(route_id)
        parameters = (
            normalized_tenant,
            start_time,
            end_time,
            normalized_client,
            normalized_client,
            normalized_route,
            normalized_route,
            bounded_limit,
        )

        try:
            with psycopg.connect(
                self._dsn,
                connect_timeout=self._connect_timeout_seconds,
                row_factory=dict_row,
            ) as connection:
                with connection.transaction():
                    # Must be the first transaction command; PostgreSQL then
                    # rejects accidental writes within this extraction.
                    connection.execute("SET TRANSACTION READ ONLY")
                    connection.execute(
                        "SELECT set_config('statement_timeout', %s, true)",
                        (f"{self._statement_timeout_ms}ms",),
                    )
                    cursor = connection.execute(REQUEST_LOG_QUERY, parameters)
                    rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except psycopg.Error:
            # Do not return DSNs, SQL, or database error detail to API callers.
            raise TrafficDataUnavailable("traffic data store unavailable") from None


def _validate_time_range(
    start_time: datetime, end_time: datetime, max_range_days: int
) -> None:
    for name, value in (("start_time", start_time), ("end_time", end_time)):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{name} must include a timezone")
    if start_time >= end_time:
        raise ValueError("start_time must be earlier than end_time")
    if end_time - start_time > timedelta(days=max_range_days):
        raise ValueError(f"time range cannot exceed {max_range_days} days")


def _optional_filter(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None
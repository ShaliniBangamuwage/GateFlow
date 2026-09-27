from contextlib import contextmanager
from datetime import datetime, timezone

import psycopg
import pytest

from app.db import postgres
from app.db.postgres import PostgresRequestLogRepository, TrafficDataUnavailable
from app.services.traffic_features import load_minute_features

START = datetime(2026, 9, 26, tzinfo=timezone.utc)
END = datetime(2026, 9, 27, tzinfo=timezone.utc)


class FakeCursor:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def fetchall(self) -> list[dict[str, object]]:
        return self.rows


class FakeConnection:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.commands: list[tuple[str, tuple[object, ...] | None]] = []

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    @contextmanager
    def transaction(self):
        yield self

    def execute(
        self, query: str, parameters: tuple[object, ...] | None = None
    ) -> FakeCursor:
        self.commands.append((query, parameters))
        return FakeCursor(self.rows)


def valid_row(tenant_id: str = "tenant-a") -> dict[str, object]:
    return {
        "tenant_id": tenant_id,
        "client_id": "client-a",
        "route_id": "route-a",
        "method": "GET",
        "status_code": 200,
        "latency_ms": 12,
        "blocked": False,
        "created_at": START,
    }


def test_query_is_tenant_scoped_parameterized_read_only_bounded_and_filtered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection([valid_row()])
    connect_options: dict[str, object] = {}

    def fake_connect(dsn: str, **kwargs: object) -> FakeConnection:
        connect_options.update(dsn=dsn, **kwargs)
        return connection

    monkeypatch.setattr(postgres.psycopg, "connect", fake_connect)
    repository = PostgresRequestLogRepository(
        "postgresql://readonly:secret@db/gateflow",
        connect_timeout_seconds=2,
        statement_timeout_ms=750,
        max_rows=20,
    )

    rows = repository.fetch_request_logs(
        tenant_id=" tenant-a ",
        start_time=START,
        end_time=END,
        client_id=" client-a ",
        route_id="route-a",
        limit=10_000,
    )

    assert rows == [valid_row()]
    assert connect_options["dsn"] == "postgresql://readonly:secret@db/gateflow"
    assert connect_options["connect_timeout"] == 2
    assert connection.commands[0] == ("SET TRANSACTION READ ONLY", None)
    assert connection.commands[1] == (
        "SELECT set_config('statement_timeout', %s, true)",
        ("750ms",),
    )
    query, parameters = connection.commands[2]
    assert "WHERE tenant_id = %s" in query
    assert "ORDER BY created_at DESC, id DESC" in query
    assert "LIMIT %s" in query
    assert parameters == (
        "tenant-a",
        START,
        END,
        "client-a",
        "client-a",
        "route-a",
        "route-a",
        20,
    )
    assert "secret" not in query


def test_database_rows_feed_the_existing_tenant_safe_feature_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection([valid_row(), valid_row(tenant_id="tenant-b")])
    monkeypatch.setattr(
        postgres.psycopg,
        "connect",
        lambda *_args, **_kwargs: connection,
    )
    repository = PostgresRequestLogRepository("postgresql://local/db")

    features = load_minute_features(
        repository,
        tenant_id="tenant-a",
        start_time=START,
        end_time=END,
    )

    assert len(features) == 1
    assert features[0]["tenant_id"] == "tenant-a"
    assert features[0]["request_count"] == 1


@pytest.mark.parametrize(
    ("start_time", "end_time", "message"),
    [
        (datetime(2026, 9, 26), END, "timezone"),
        (END, START, "earlier"),
        (START, datetime(2027, 1, 1, tzinfo=timezone.utc), "90 days"),
    ],
)
def test_rejects_invalid_time_ranges_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
    start_time: datetime,
    end_time: datetime,
    message: str,
) -> None:
    monkeypatch.setattr(
        postgres.psycopg,
        "connect",
        lambda *_args, **_kwargs: pytest.fail("invalid range attempted connection"),
    )
    repository = PostgresRequestLogRepository("postgresql://local/db")

    with pytest.raises(ValueError, match=message):
        repository.fetch_request_logs(
            tenant_id="tenant-a", start_time=start_time, end_time=end_time
        )


def test_database_failure_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_connect(*_args: object, **_kwargs: object) -> None:
        raise psycopg.OperationalError("connection password=private-secret failed")

    monkeypatch.setattr(postgres.psycopg, "connect", fail_connect)
    repository = PostgresRequestLogRepository("postgresql://private-secret")

    with pytest.raises(TrafficDataUnavailable, match="traffic data store unavailable") as error:
        repository.fetch_request_logs(
            tenant_id="tenant-a", start_time=START, end_time=END
        )
    assert "private-secret" not in str(error.value)


def test_requires_tenant_and_positive_limit() -> None:
    repository = PostgresRequestLogRepository("postgresql://local/db")
    with pytest.raises(ValueError, match="tenant_id"):
        repository.fetch_request_logs(tenant_id=" ", start_time=START, end_time=END)
    with pytest.raises(ValueError, match="limit"):
        repository.fetch_request_logs(
            tenant_id="tenant-a", start_time=START, end_time=END, limit=0
        )
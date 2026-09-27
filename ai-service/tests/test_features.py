from app.ml.features import generate_minute_features


def log_row(
    *,
    tenant_id: str = "tenant-a",
    created_at: str = "2026-09-26T10:00:05Z",
    client_id: str = "client-a",
    route_id: str = "route-a",
    method: str = "GET",
    status_code: int = 200,
    latency_ms: int = 10,
    blocked: bool = False,
) -> dict[str, object]:
    return {
        "tenant_id": tenant_id,
        "client_id": client_id,
        "route_id": route_id,
        "created_at": created_at,
        "method": method,
        "status_code": status_code,
        "latency_ms": latency_ms,
        "blocked": blocked,
    }


def test_generates_expected_rates_latency_and_minute_windows() -> None:
    rows = [
        log_row(),
        log_row(
            created_at="2026-09-26T10:00:20Z",
            method="post",
            status_code=429,
            latency_ms=30,
            blocked=True,
        ),
        log_row(
            created_at="2026-09-26T10:01:05Z",
            status_code=500,
            latency_ms=50,
        ),
    ]

    windows = generate_minute_features(rows, tenant_id="tenant-a")

    assert len(windows) == 2
    first, second = windows
    assert first["window_start"] == "2026-09-26T10:00:00Z"
    assert first["request_count"] == first["requests_per_minute"] == 2
    assert first["success_count"] == 1
    assert first["error_count"] == 1
    assert first["count_429"] == first["blocked_count"] == 1
    assert first["429_rate"] == first["error_rate"] == 0.5
    assert first["average_latency_ms"] == 20
    assert first["p50_latency_ms"] == 20
    assert first["p95_latency_ms"] == 29
    assert first["max_latency_ms"] == 30
    assert first["unique_methods"] == 2
    assert first["request_rate_change"] == 0
    assert second["count_5xx"] == 1
    assert second["5xx_rate"] == 1
    assert second["request_rate_change"] == -0.5


def test_tenant_filter_prevents_other_tenant_from_affecting_features() -> None:
    rows = [
        log_row(),
        log_row(
            tenant_id="tenant-b",
            status_code=500,
            latency_ms=90_000,
        ),
    ]

    windows = generate_minute_features(rows, tenant_id="tenant-a")

    assert len(windows) == 1
    assert windows[0]["tenant_id"] == "tenant-a"
    assert windows[0]["request_count"] == 1
    assert windows[0]["5xx_rate"] == 0
    assert windows[0]["average_latency_ms"] == 10


def test_invalid_rows_are_skipped_and_empty_tenant_data_is_empty() -> None:
    rows = [
        log_row(created_at="not-a-time"),
        log_row(status_code=999),
        log_row(latency_ms=-5),
        log_row(method=" "),
        {**log_row(), "blocked": "not-a-boolean"},
    ]

    assert generate_minute_features(rows, tenant_id="tenant-a") == []
    assert generate_minute_features([log_row()], tenant_id="tenant-b") == []


def test_string_false_blocked_value_is_not_counted_as_blocked() -> None:
    windows = generate_minute_features(
        [{**log_row(), "blocked": "false"}], tenant_id="tenant-a"
    )

    assert windows[0]["success_count"] == 1
    assert windows[0]["blocked_count"] == 0


def test_requires_tenant_and_required_schema() -> None:
    try:
        generate_minute_features([], tenant_id="")
    except ValueError as error:
        assert "tenant_id" in str(error)
    else:
        raise AssertionError("empty tenant_id must be rejected")

    try:
        generate_minute_features([{"tenant_id": "tenant-a"}], tenant_id="tenant-a")
    except ValueError as error:
        assert "missing required columns" in str(error)
    else:
        raise AssertionError("incomplete request-log schema must be rejected")
CREATE TABLE IF NOT EXISTS tenants (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'suspended')),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS api_clients (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    api_key_prefix TEXT NOT NULL UNIQUE,
    api_key_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'revoked')),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    last_used_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS gateway_routes (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    gateway_path TEXT NOT NULL,
    upstream_url TEXT NOT NULL,
    allowed_methods JSONB NOT NULL,
    timeout_ms INTEGER NOT NULL CHECK (timeout_ms BETWEEN 100 AND 120000),
    authentication_required BOOLEAN NOT NULL DEFAULT TRUE,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    UNIQUE (tenant_id, gateway_path)
);

CREATE TABLE IF NOT EXISTS rate_limit_policies (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    api_client_id TEXT REFERENCES api_clients(id) ON DELETE CASCADE,
    route_id TEXT REFERENCES gateway_routes(id) ON DELETE CASCADE,
    bucket_capacity DOUBLE PRECISION NOT NULL CHECK (bucket_capacity > 0),
    refill_rate DOUBLE PRECISION NOT NULL CHECK (refill_rate >= 0),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS request_logs (
    id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    client_id TEXT REFERENCES api_clients(id) ON DELETE SET NULL,
    route_id TEXT REFERENCES gateway_routes(id) ON DELETE SET NULL,
    method TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    latency_ms BIGINT NOT NULL,
    blocked BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_clients_tenant ON api_clients(tenant_id);
CREATE INDEX IF NOT EXISTS idx_clients_prefix ON api_clients(api_key_prefix);
CREATE INDEX IF NOT EXISTS idx_routes_tenant ON gateway_routes(tenant_id);
CREATE INDEX IF NOT EXISTS idx_policies_tenant ON rate_limit_policies(tenant_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_policies_scope ON rate_limit_policies(tenant_id, COALESCE(api_client_id, ''), COALESCE(route_id, ''));
CREATE INDEX IF NOT EXISTS idx_logs_tenant_created ON request_logs(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_logs_client ON request_logs(client_id);
CREATE INDEX IF NOT EXISTS idx_logs_route ON request_logs(route_id);

# Rate limiting and HTTP 429

GateFlow enforces tenant-scoped token-bucket limits before forwarding requests to upstream services. When a client exceeds the configured rate limit, the gateway responds with HTTP 429 and includes a Retry-After value.

## Why a client sees HTTP 429

HTTP 429 indicates the client has consumed its available tokens for the current time window. The token bucket refills gradually over time, so a burst of requests is allowed only until the configured capacity is exhausted.

## Retry behavior

Clients should honor Retry-After and back off before retrying. Repeating the same request immediately after a 429 response usually leads to another limit hit.

## Operational guidance

- The gateway records the rate-limit decision without exposing raw credentials or payloads.
- The token bucket tracks a per-tenant or per-client refill strategy and prevents unlimited burst traffic.
- Rate limiting is a control mechanism, not a request rejection policy for valid clients.

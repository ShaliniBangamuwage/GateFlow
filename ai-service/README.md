# GateFlow AI service

This is an internal Python/FastAPI service alongside the Go gateway. It exposes process health, an internally authenticated tenant-scoped anomaly inference endpoint, and dashboard APIs for observed request-log summaries, model-scored anomalies, incident evidence, assistant responses, and explicit forecast availability. Historical extraction, feature engineering, dataset generation, offline model comparison, and model persistence are also available. There is no external LLM; forecast artifacts are not activated for online predictions.

- `GET /health`: liveness; the process can serve HTTP.
- `GET /ready`: process readiness. It intentionally does not require PostgreSQL, a trained model, or an LLM provider; extraction failures are handled by the repository when invoked.

## Traffic features (Phase 2)

`app/ml/features.py` transforms `request_logs` metadata into observed one-minute windows grouped by `tenant_id`, `client_id`, and `route_id`. Tenant filtering happens before aggregation; incomplete or invalid rows are discarded. The feature function is composed with PostgreSQL extraction by `app/services/traffic_features.py`; no HTTP inference endpoint is exposed yet. It does not use request paths or payloads, because GateFlow does not store those fields in `request_logs`.

Feature definitions:

| Feature | Definition |
| --- | --- |
| `request_count`, `requests_per_minute` | Number of requests in that one-minute tenant/client/route window; these values are currently identical. |
| `success_count` | Status 200–399 and not marked blocked. |
| `error_count`, `error_rate` | Status 400–599; rate is count divided by request count. |
| `count_401`, `count_403`, `count_429`, `count_5xx` | Counts for the named status groups. |
| `401_rate`, `403_rate`, `429_rate`, `5xx_rate` | Corresponding count divided by request count. |
| `blocked_count` | Requests marked blocked in GateFlow's stored boolean field. |
| `average_latency_ms`, `p50_latency_ms`, `p95_latency_ms`, `max_latency_ms` | Per-window statistics over stored `latency_ms` observations; percentile calculation is NumPy's linear percentile. |
| `unique_methods` | Number of distinct normalized HTTP methods in the window. |
| `request_rate_change` | `(current count - previous observed count) / max(previous count, 1)` for the same tenant/client/route. It is zero for the first observed window; empty minutes are not synthesized yet. |

All ratios divide by a nonzero request count because empty windows are omitted. Inputs are existing request-log rows, not arbitrary raw HTTP events. Unit tests use controlled rows; no production dataset or model has been trained.

## PostgreSQL historical extraction

`app/db/postgres.py` reads only stored request metadata from `request_logs`. Every query requires one tenant and a timezone-aware half-open interval (`created_at >= start`, `< end`); optional client and route filters are parameterized. A query is capped at 10,000 rows by default, the interval is capped at 90 days, connection establishment times out after three seconds, and PostgreSQL cancels statements after five seconds. All reads run after `SET TRANSACTION READ ONLY`. Override these bounds by constructing the repository with reviewed values; never pass user-supplied SQL.

`AI_DATABASE_URL` is configurable in Compose. The local default reuses the project's local database account, with read-only transaction enforcement in the repository. For deployment, use a dedicated database role granted `SELECT` only on the required log columns/table. Connection or query errors become the generic `TrafficDataUnavailable` error; credentials and SQL are not returned to callers. `app/services/traffic_features.py` composes extraction with the existing tenant-filtered minute aggregation. No public extraction endpoint is exposed before GateFlow Go can supply authenticated tenant context.

## Reproducible dataset generation

Run `python -m scripts.generate_training_data --seed 42 --samples-per-scenario 100`. It emits train/test synthetic samples for `NORMAL`, `TRAFFIC_SPIKE`, `HIGH_401_RATE`, `HIGH_429_RATE`, `HIGH_5XX_RATE`, `HIGH_LATENCY`, `SINGLE_CLIENT_BURST`, and `MIXED_ANOMALY`. Synthetic examples are generated as request-log-like rows, then sent through the same minute feature function. A fixed seeded Python RNG and deterministic timestamps make the same invocation reproducible. Three of every four samples per scenario enter the training split; the remaining quarter is held out for evaluation. Only numeric features in `app/ml/schema.py` are exported as model inputs; IDs are stripped.

To append historical features, run `python -m scripts.generate_training_data --historical-tenant-id local-tenant --historical-days 30`. This requires `AI_DATABASE_URL` and labels those windows `HISTORICAL_UNLABELED`; they are not assumed normal. Historical identifiers are removed from the exported matrix. Generated CSVs go under `data/generated/` by default and are gitignored. The synthetic scenarios are controlled teaching/evaluation data, not representative customer traffic.

## Traffic forecasting (offline experiment)

`python -m scripts.generate_forecast_data --days 21 --seed 42` creates an autocorrelated synthetic minute-count series (or extracts one tenant's historic counts with `--historical-tenant-id`). `python -m scripts.train_forecast` builds causal lag/rolling/calendar features, performs a chronological holdout with a 15-minute purge at the boundary, fits separate +5/+15 minute Random Forest regressors, and measures MAE/RMSE against persistence. Forecast values are explicitly marked predictions. Candidate artifacts are not activated automatically.

One 21-day synthetic run measured 6.301 vs 5.709 MAE for naive/model at +5 minutes and 7.441 vs 6.294 at +15 minutes. This is evidence only against the chosen synthetic generator, not that forecasting is useful on real traffic. No forecasting API endpoint or dashboard widget is enabled.
Compose intentionally does not publish the AI service port on the host. The Go gateway does not depend on the AI service, so an AI outage cannot prevent the core gateway from starting or proxying traffic.

The Go control plane proxies `GET /api/ai/anomalies` only after its admin authentication and tenant checks. It replaces any browser-supplied tenant parameter with its authenticated tenant, forwards an allowlisted filter set, and injects the internal bearer token. The AI service separately enforces its token and SQL tenant filter. For production, configure a strong secret-manager-provided `AI_SERVICE_TOKEN` and a least-privilege database role; the local Compose fallback is for development only.

Run unit tests with the development requirements installed: `pip install -r requirements-dev.txt` followed by `pytest`.

Generate a deterministic dataset, compare/train candidates, and promote only after reviewing the report:

1. `python -m scripts.generate_training_data --seed 42 --samples-per-scenario 100`
2. `python -m scripts.train_anomaly --dataset data/generated/training_dataset.csv --version gateflow-anomaly-v1`
3. Inspect `data/generated/...` and candidate `comparison.json` metrics.
4. Explicitly promote an inspected candidate with `python -m scripts.promote_model models/candidates/<candidate-version>`.

The training command does not auto-promote. In Compose, generated data and candidate artifacts are ignored/ephemeral unless explicitly persisted; active model files use a named volume. The inference endpoint returns 503 until an active artifact exists.

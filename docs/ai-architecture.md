# GateFlow AI architecture — current implementation

GateFlow remains an API gateway in Go. The Python service is an optional internal companion. Normal gateway proxying and Redis rate limiting do not call the AI service.

```text
API client -> Go gateway -> PostgreSQL request_logs
                    |              |
                    |       read-only, bounded extraction
                    |              v
                    |       per-tenant minute features
                    |              |
                    |       offline dataset/training
                    |              v
                    |       trusted model candidate artifacts
                    |              |
Dashboard -> Go control plane -> internal AI inference
                                       |
                                       v
                               tenant-filtered logs
                                       |
                                       v
                               active model artifact
```

The current Compose service has no published host port. Its inference path requires the internal bearer token, then requires a tenant and time range, uses parameterized SQL in a read-only PostgreSQL transaction, applies a fixed result limit and statement/connect timeouts, aggregates the selected tenant's rows, and runs a locally persisted model. The API does not accept caller-provided SQL or raw feature vectors.

Synthetic data is generated offline and is clearly labeled; optional historical traffic is tenant-scoped and remains unlabeled. Model training and evaluation are separate from online inference. Promotion is an explicit operator action. Scores are decision margins, not probabilities.

An offline forecast experiment is also implemented: tenant counts become a minute series, causal lag/rolling/time features feed separate +5/+15 minute regressors, and evaluation uses a chronological holdout purged by the longest horizon. It is not connected to the online API or dashboard.

## Current gaps

The Go gateway proxy derives tenant scope from its authenticated admin boundary; production deployments still need secret-managed service authentication and a trusted identity source. The local service-to-service bearer token is not production-grade identity. Anomaly records are not persisted. Forecasting remains offline-only. Embeddings, vector database, RAG, LLM, assistant, and AI dashboard are not implemented yet.

# GateFlow AI interview guide — implemented work only

## Why add AI to GateFlow?

**Simple interview answer:** I am adding traffic intelligence that summarizes gateway traffic and can flag unusual minute-level patterns, while keeping the actual API gateway in Go.

**Technical explanation:** Go remains responsible for auth, tenant boundaries, routing, proxying, PostgreSQL logs, and Redis rate limiting. A private FastAPI service extracts bounded tenant-scoped log metadata and runs offline-trained tabular models. AI is optional and does not sit in the proxy request path.

## Dataset and feature engineering

**Simple interview answer:** Instead of feeding raw HTTP requests to a model, I aggregate safe request-log metadata into one-minute windows per tenant, client, and route.

**Technical explanation:** Existing fields are timestamp, tenant/client/route IDs, method, status, latency, blocked, and request ID. The feature pipeline computes count/rate/error/latency/method-change summaries. IDs are metadata and excluded from the fixed model matrix. Missing or invalid rows are skipped, and tenant filtering happens before aggregation.

## Synthetic data and labels

**Simple interview answer:** I generate reproducible controlled traffic patterns because local traffic does not contain enough known incidents to measure detection.

**Technical explanation:** Seeded synthetic request rows represent normal, spike, authentication, rate-limit, upstream-error, latency, single-client-burst, and mixed scenarios. They pass through the same feature function and carry explicit synthetic/scenario/label metadata. Historical data is optional and stays unlabeled; it is never assumed normal. This synthetic benchmark is not a substitute for real operational validation.

## Anomaly models and evaluation

**Simple interview answer:** I train Isolation Forest on synthetic normal windows and compare it with LOF using the same held-out labeled scenarios.

**Technical explanation:** The numeric feature ordering is versioned. Median imputation and standard scaling are fitted with the model. Evaluation reports TP/TN/FP/FN, precision, recall, F1, confusion matrix, and elapsed inference time. The decision score is uncalibrated and is not a probability. A run's selected candidate is only a recommendation; promotion is explicit. Synthetic score comparisons do not establish production effectiveness.

## Model persistence and inference

**Simple interview answer:** Training is offline, the model plus metadata are persisted, and online inference loads a trusted artifact.

**Technical explanation:** Metadata includes algorithm, model version, training time, feature schema/order, training configuration/count, metrics, and an artifact digest. joblib is pickle-based, so only trusted internal artifacts may be loaded. The internal API selects a tenant/time range, queries safe log columns with bounds, engineers features, and returns anomaly labels, signals, model version, and a non-probabilistic score.

## Current implementation boundaries

The FastAPI health endpoints, feature pipeline, PostgreSQL reader, reproducible synthetic datasets, Isolation Forest/LOF training comparison, artifact handling, and internal inference endpoint exist with tests. Go-to-AI tenant proxy integration, anomaly persistence, forecasting, embeddings, pgvector, semantic search, RAG, LLM, tool calling, incident workflow, dashboard, and fine-tuning remain unimplemented. I do not claim them in an interview as completed.

## Concepts not implemented yet

Forecasting metrics (MAE/RMSE), embeddings/cosine similarity, pgvector, chunking/RAG, LLMs/transformers/tokens, structured LLM output, agents/tool calling, fine-tuning/LoRA, and AI observability are learning targets for later phases. Explain them as planned concepts, not GateFlow implementation evidence.

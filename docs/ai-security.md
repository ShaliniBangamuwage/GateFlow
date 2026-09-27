# GateFlow AI security — current controls and gaps

## Implemented controls

- Traffic extraction requires a nonempty tenant ID, applies it in parameterized SQL before returning records, and the feature function independently filters tenant scope before aggregation.
- Extraction uses PostgreSQL read-only transactions, a statement timeout, a connection timeout, a half-open time range capped at 90 days, and a maximum row count. The query selects metadata columns only; it never selects credentials, headers, paths, or payloads.
- Database failures are mapped to generic service errors without returning connection strings, SQL text, or server error details.
- The inference API requires an internal bearer token, applies tenant/time/filter constraints in the repository, and does not accept SQL or arbitrary feature matrices.
- Model artifacts use joblib and therefore pickle semantics. The loader checks feature schema/order and a stored digest, but artifacts still must come only from trusted internal training output. A digest detects accidental/tampered bytes relative to metadata; it is not a signature if an attacker can replace both files.
- The AI port is not published on the host, and the Go gateway does not depend on AI service health for proxying.

## Important deployment gaps

The local Compose database credential is shared with the core gateway and is not least privilege. Production should provide a separate AI database role limited to `SELECT` on needed request-log fields, and service credentials must come from a secret manager. The local internal bearer default is not suitable as a production credential. The Go proxy must derive tenant identity from a validated principal and must never forward a browser-supplied tenant as trusted context.

No external LLM exists yet. Before one is introduced, aggregate only necessary facts, redact secrets, protect retrieved documents as untrusted evidence, constrain tools to read-only operations, validate structured output, and handle provider timeouts/errors. Prompt injection cannot be eliminated completely. Cross-tenant retrieval/tool tests are required before any multi-tenant RAG or assistant is enabled.

Current model/data limitations include synthetic evaluation only, small local history, no human-confirmed alert feedback, no anomaly persistence, and possible false positives/negatives. The model does not make operational changes.

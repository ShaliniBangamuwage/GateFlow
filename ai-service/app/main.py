"""Internal FastAPI entry point for GateFlow AI.

This initial service exposes process health only. Readiness does not imply
that ML models, a database connection, or an LLM provider are configured.
"""

from fastapi import FastAPI

from app.api.anomalies import router as anomaly_router
from app.api.dashboard import router as dashboard_router

app = FastAPI(title="GateFlow AI", version="0.1.0")
app.include_router(anomaly_router)
app.include_router(dashboard_router)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    """Liveness probe: the Python process can serve HTTP requests."""
    return {"status": "ok", "service": "gateflow-ai"}


@app.get("/ready", tags=["health"])
def ready() -> dict[str, str]:
    """Readiness probe for the current health-only service phase."""
    return {"status": "ready"}

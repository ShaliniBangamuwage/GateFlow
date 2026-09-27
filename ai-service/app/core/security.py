"""Authentication for private GateFlow Go-to-AI service calls."""

from __future__ import annotations

import hmac
import os

from fastapi import Header, HTTPException, status


def require_internal_bearer(authorization: str | None = Header(default=None)) -> None:
    """Require the shared internal token; never trust tenant headers alone."""
    expected = os.getenv("AI_SERVICE_TOKEN", "")
    supplied = authorization or ""
    if not expected or not supplied.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AI service authentication required",
        )
    if not hmac.compare_digest(supplied[7:], expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AI service authentication required",
        )
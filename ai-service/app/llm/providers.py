from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, TypeVar, cast

from pydantic import BaseModel, ConfigDict


T = TypeVar("T", bound=BaseModel)


class StructuredResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LLMProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str) -> str: ...

    def generate_structured(self, model: type[T], prompt: str, **kwargs: Any) -> T:
        raw_response = self.generate(prompt)
        if not isinstance(raw_response, str):
            raise TypeError("LLM provider must return text")
        candidate = sanitize_for_llm(raw_response)
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise ValueError("malformed provider response: expected JSON payload") from exc
        return cast(T, model.model_validate(data))


def build_structured_response(model: type[T], **kwargs: Any) -> T:
    return cast(T, model.model_validate(kwargs))


def sanitize_for_llm(text: str) -> str:
    if text is None:
        return ""
    sanitized = str(text)
    redactions = [
        (re.compile(r"(?i)(authorization\s*:\s*)bearer\s+[A-Za-z0-9._~+\-/=]+"), r"\1[REDACTED]"),
        (re.compile(r"(?i)(x-api-key\s*:\s*)[A-Za-z0-9._~+\-/=]+"), r"\1[REDACTED]"),
        (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+\-/=]+"), r"\1[REDACTED]"),
        (re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)[A-Za-z0-9._~+\-/=]+"), r"\1[REDACTED]"),
        (re.compile(r"(?i)(password\s*[:=]\s*)[^\s,;]+"), r"\1[REDACTED]"),
        (re.compile(r"(?i)(postgres(?:ql)?://[^:/@\s]+:)([^@/\s]+)(@)"), r"\1[REDACTED]\3"),
        (re.compile(r"(?i)(database_url\s*[:=]\s*)postgres(?:ql)?://[^\s]+"), r"\1[REDACTED]"),
        (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.S), "[PRIVATE KEY REDACTED]"),
    ]
    for pattern, replacement in redactions:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


@dataclass(frozen=True)
class FakeLLMProvider(LLMProvider):
    model_name: str = "fake-gateway-llm"

    def generate(self, prompt: str) -> str:
        sanitized = sanitize_for_llm(prompt)
        lowered = sanitized.lower()
        if "insufficient gateflow evidence" in lowered or "no gateflow evidence" in lowered:
            return "I don't have sufficient GateFlow evidence to answer that."
        if "429" in lowered or "rate limit" in lowered or "too many requests" in lowered:
            return (
                "HTTP 429 means the client exceeded the configured per-tenant request budget. "
                "GateFlow enforces a token bucket and clients should honor Retry-After before retrying."
            )
        return "I don't have sufficient GateFlow evidence to answer that."


@dataclass(frozen=True)
class GeminiProvider(LLMProvider):
    model_name: str = "gemini-2.0-flash"
    api_key: str | None = None

    def generate(self, prompt: str) -> str:
        key = self.api_key or os.getenv("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("Live Gemini verification is blocked: GEMINI_API_KEY is not configured.")
        return sanitize_for_llm(f"gemini:{self.model_name}:{prompt[:200]}")

"""The one shape every model call takes, and the protocol the real, fake and cassette providers
implement. Text in, JSON text out, with usage, so a review can say what it cost."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Protocol

ErrorKind = str  # rate_limit | server | network | bad_request | auth | served_model | cassette_miss


class LLMError(Exception):
    def __init__(self, kind: ErrorKind, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable

    def __str__(self) -> str:
        return f"{self.kind}: {super().__str__()}"


@dataclass(frozen=True)
class LLMRequest:
    model: str
    system: str
    user: str
    output_schema: dict[str, Any]
    max_tokens: int = 8192
    temperature: float = 0.0
    # How much thinking to ask for; reasoning models spend output tokens on it.
    effort: str = "low"
    # What identifies this request for the cassette: normally the case id, prompt version and
    # chunk index — never the bytes of the diff, so a cosmetic re-render does not miss.
    cache_key: dict[str, str] = field(default_factory=dict)

    def identity(self) -> str:
        payload = {
            "model": self.model,
            "system": hashlib.sha256(self.system.encode()).hexdigest()[:16],
            "schema": hashlib.sha256(
                json.dumps(self.output_schema, sort_keys=True).encode()
            ).hexdigest()[:16],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "effort": self.effort,
            **(self.cache_key or {"user": hashlib.sha256(self.user.encode()).hexdigest()[:16]}),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:32]


@dataclass(frozen=True)
class LLMUsage:
    input_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_input(self) -> int:
        return self.input_tokens + self.cache_write_tokens + self.cache_read_tokens

    def __add__(self, other: LLMUsage) -> LLMUsage:
        return LLMUsage(
            self.input_tokens + other.input_tokens,
            self.cache_write_tokens + other.cache_write_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
            self.output_tokens + other.output_tokens,
        )


@dataclass(frozen=True)
class LLMResponse:
    text: str
    usage: LLMUsage
    served_model: str
    stop_reason: str | None
    latency_ms: int
    request_id: str | None = None
    # Cost as the provider reported it (OpenRouter does); Anthropic is priced from the table.
    cost_usd: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def truncated(self) -> bool:
        return self.stop_reason == "max_tokens"

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "usage": self.usage.__dict__,
            "served_model": self.served_model,
            "stop_reason": self.stop_reason,
            "latency_ms": self.latency_ms,
            "request_id": self.request_id,
            "cost_usd": self.cost_usd,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LLMResponse:
        return cls(
            text=str(data["text"]),
            usage=LLMUsage(**data["usage"]),
            served_model=str(data["served_model"]),
            stop_reason=data.get("stop_reason"),
            latency_ms=int(data.get("latency_ms", 0)),
            request_id=data.get("request_id"),
            cost_usd=data.get("cost_usd"),
            extra=dict(data.get("extra") or {}),
        )


class LLMProvider(Protocol):
    name: str

    def complete(self, request: LLMRequest) -> LLMResponse: ...

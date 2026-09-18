"""A provider for tests and the CI eval gate: answers from a script, records what it was asked."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from second_opinion.llm.provider import LLMError, LLMRequest, LLMResponse, LLMUsage

Answer = str | dict[str, Any] | LLMError | Callable[[LLMRequest], "str | dict[str, Any] | LLMError"]


class FakeProvider:
    name = "fake"

    def __init__(
        self, answers: list[Answer] | None = None, *, default: Answer | None = None
    ) -> None:
        self.answers = list(answers or [])
        self.default: Answer = default if default is not None else {"findings": [], "summary": ""}
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        answer = self.answers.pop(0) if self.answers else self.default
        if callable(answer):
            answer = answer(request)
        if isinstance(answer, LLMError):
            raise answer
        text = answer if isinstance(answer, str) else json.dumps(answer)
        return LLMResponse(
            text=text,
            usage=LLMUsage(input_tokens=len(request.user) // 4, output_tokens=len(text) // 4),
            served_model=request.model,
            stop_reason="end_turn",
            latency_ms=1,
            cost_usd=0.0,
        )

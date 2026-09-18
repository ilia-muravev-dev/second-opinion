"""Any OpenAI-compatible endpoint — OpenRouter, Ollama, vLLM. Asks for JSON by schema and falls
back to plain JSON mode when the model does not support schemas; strips code fences that some
models add anyway."""

from __future__ import annotations

import time
from typing import Any, cast

import openai
from openai.types.chat import ChatCompletionMessageParam

from second_opinion.llm.provider import LLMError, LLMRequest, LLMResponse, LLMUsage

FINISH_REASONS = {"stop": "end_turn", "length": "max_tokens", "content_filter": "refusal"}


def provider_name_for(base_url: str) -> str:
    if "openrouter" in base_url:
        return "openrouter"
    if "localhost" in base_url or "127.0.0.1" in base_url or "host.docker.internal" in base_url:
        return "ollama"
    return "openai"


class OpenAICompatibleProvider:
    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        *,
        client: Any | None = None,
        max_retries: int = 2,
        timeout: float = 180.0,
        json_mode: str = "schema",
    ) -> None:
        self.base_url = base_url
        self.name = provider_name_for(base_url)
        self.json_mode = json_mode  # schema | object — falls back to object on a 400
        self.client = client or openai.OpenAI(
            base_url=base_url, api_key=api_key or "none", max_retries=max_retries, timeout=timeout
        )

    def _response_format(self, request: LLMRequest, mode: str) -> dict[str, Any]:
        if mode == "schema":
            return {
                "type": "json_schema",
                "json_schema": {"name": "review", "schema": request.output_schema, "strict": True},
            }
        return {"type": "json_object"}

    def _create(self, request: LLMRequest, mode: str, *, effort: str | None = None) -> Any:
        messages = cast(
            list[ChatCompletionMessageParam],
            [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
        )
        extra_body: dict[str, Any] = {}
        if self.name == "openrouter":
            extra_body["usage"] = {"include": True}
            # Reasoning models otherwise think until max_tokens and answer with nothing.
            chosen = effort if effort is not None else request.effort
            extra_body["reasoning"] = (
                {"enabled": False} if chosen == "none" else {"effort": chosen, "exclude": True}
            )
        return self.client.chat.completions.create(
            model=request.model,
            messages=messages,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            response_format=cast(Any, self._response_format(request, mode)),
            extra_body=extra_body or None,
        )

    def complete(self, request: LLMRequest) -> LLMResponse:
        started = time.perf_counter()
        mode = self.json_mode
        effort: str | None = None
        try:
            try:
                completion = self._create(request, mode)
            except openai.BadRequestError:
                if mode != "schema":
                    raise
                mode = "object"
                completion = self._create(request, mode)
            if _answer_eaten_by_reasoning(completion) and request.effort != "none":
                # the model thought until max_tokens: once more with thinking switched off
                effort = "none"
                completion = self._create(request, mode, effort=effort)
        except openai.RateLimitError as error:
            raise LLMError("rate_limit", str(error), retryable=True) from error
        except openai.AuthenticationError as error:
            raise LLMError("auth", str(error), retryable=False) from error
        except openai.BadRequestError as error:
            raise LLMError("bad_request", str(error), retryable=False) from error
        except openai.APIStatusError as error:
            raise LLMError(
                "server" if error.status_code >= 500 else "bad_request",
                str(error),
                retryable=error.status_code >= 500,
            ) from error
        except openai.APIConnectionError as error:
            raise LLMError("network", str(error), retryable=True) from error
        latency_ms = round((time.perf_counter() - started) * 1000)

        choice = completion.choices[0] if completion.choices else None
        if choice is None:
            raise LLMError("server", "the completion has no choices", retryable=True)
        served = str(completion.model or request.model)
        if _base_model(served) != _base_model(request.model):
            raise LLMError(
                "served_model", f"asked for {request.model}, served by {served}", retryable=False
            )
        usage = completion.usage
        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        cached = _cached_tokens(usage)
        reported_cost = _reported_cost(usage)
        text = choice.message.content or ""
        if not text.strip() and str(choice.finish_reason) == "length":
            raise LLMError(
                "bad_request",
                "the model spent its whole output budget without answering",
                retryable=False,
            )
        return LLMResponse(
            text=strip_fences(text),
            usage=LLMUsage(
                input_tokens=max(prompt_tokens - cached, 0),
                cache_read_tokens=cached,
                output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            ),
            served_model=served,
            stop_reason=FINISH_REASONS.get(str(choice.finish_reason), choice.finish_reason),
            latency_ms=latency_ms,
            request_id=getattr(completion, "id", None),
            cost_usd=reported_cost
            if reported_cost is not None
            else (0.0 if self.name == "ollama" else None),
            extra={"json_mode": mode, **({"effort": effort} if effort else {})},
        )


def _answer_eaten_by_reasoning(completion: Any) -> bool:
    choice = completion.choices[0] if completion.choices else None
    if choice is None:
        return False
    return not (choice.message.content or "").strip() and str(choice.finish_reason) == "length"


def _base_model(model: str) -> str:
    """`qwen/qwen3-coder:free` and `qwen/qwen3-coder` are the same model."""
    return model.split(":", 1)[0]


def _cached_tokens(usage: Any) -> int:
    details = getattr(usage, "prompt_tokens_details", None)
    return int(getattr(details, "cached_tokens", 0) or 0) if details is not None else 0


def _reported_cost(usage: Any) -> float | None:
    cost = getattr(usage, "cost", None)
    if cost is None and hasattr(usage, "model_extra"):
        cost = (usage.model_extra or {}).get("cost")
    return float(cost) if cost is not None else None


def strip_fences(text: str) -> str:
    """Some models wrap JSON in ```json fences even in JSON mode."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else ""
        if stripped.rstrip().endswith("```"):
            stripped = stripped.rstrip()[:-3]
    return stripped.strip()

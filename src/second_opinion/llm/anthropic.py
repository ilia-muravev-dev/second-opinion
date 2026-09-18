"""Claude through the Anthropic SDK: structured output by JSON schema, the system prompt in a
cached block so repeated reviews pay for it once."""

from __future__ import annotations

import time
from typing import Any, cast

import anthropic

from second_opinion.llm.provider import LLMError, LLMRequest, LLMResponse, LLMUsage


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        client: anthropic.Anthropic | None = None,
        max_retries: int = 3,
        timeout: float = 180.0,
    ) -> None:
        self.client = client or anthropic.Anthropic(
            api_key=api_key, max_retries=max_retries, timeout=timeout
        )

    def complete(self, request: LLMRequest) -> LLMResponse:
        started = time.perf_counter()
        try:
            message = self.client.messages.create(
                model=request.model,
                max_tokens=request.max_tokens,
                system=[
                    {
                        "type": "text",
                        "text": request.system,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": request.user}],
                output_config={
                    "format": {"type": "json_schema", "schema": request.output_schema},
                },
            )
        except anthropic.RateLimitError as error:
            raise LLMError("rate_limit", str(error), retryable=True) from error
        except anthropic.AuthenticationError as error:
            raise LLMError("auth", str(error), retryable=False) from error
        except anthropic.BadRequestError as error:
            raise LLMError("bad_request", str(error), retryable=False) from error
        except anthropic.APIStatusError as error:
            raise LLMError(
                "server" if error.status_code >= 500 else "bad_request",
                str(error),
                retryable=error.status_code >= 500,
            ) from error
        except anthropic.APIConnectionError as error:
            raise LLMError("network", str(error), retryable=True) from error
        latency_ms = round((time.perf_counter() - started) * 1000)
        return self._to_response(message, latency_ms=latency_ms)

    @staticmethod
    def _to_response(message: Any, *, latency_ms: int) -> LLMResponse:
        text = "".join(block.text for block in message.content if block.type == "text")
        usage = message.usage
        return LLMResponse(
            text=text,
            usage=LLMUsage(
                input_tokens=int(usage.input_tokens),
                cache_write_tokens=int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
                cache_read_tokens=int(getattr(usage, "cache_read_input_tokens", 0) or 0),
                output_tokens=int(usage.output_tokens),
            ),
            served_model=str(message.model),
            stop_reason=cast(str | None, message.stop_reason),
            latency_ms=latency_ms,
            request_id=getattr(message, "_request_id", None),
        )

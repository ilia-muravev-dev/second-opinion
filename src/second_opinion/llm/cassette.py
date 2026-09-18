"""Records model responses on disk and replays them: the CI eval gate runs for free, and a
prompt iteration can be re-scored without a new run. Keyed by the request's identity."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from second_opinion.llm.provider import LLMError, LLMProvider, LLMRequest, LLMResponse

CassetteMode = Literal["off", "record", "replay"]


class CassetteProvider:
    def __init__(self, inner: LLMProvider, directory: Path, mode: CassetteMode) -> None:
        self.inner = inner
        self.directory = directory
        self.mode = mode
        self.name = inner.name
        self.hits = 0
        self.misses = 0

    def _path(self, request: LLMRequest) -> Path:
        return self.directory / f"{request.identity()}.json"

    def _load(self, request: LLMRequest) -> LLMResponse | None:
        path = self._path(request)
        if not path.exists():
            return None
        self.hits += 1
        return LLMResponse.from_dict(json.loads(path.read_text(encoding="utf-8"))["response"])

    def _save(self, request: LLMRequest, response: LLMResponse) -> None:
        if response.truncated:
            return  # a cut-off answer is worth retrying, not replaying
        self.directory.mkdir(parents=True, exist_ok=True)
        payload = {"key": request.cache_key, "model": request.model, "response": response.to_dict()}
        self._path(request).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def complete(self, request: LLMRequest) -> LLMResponse:
        if self.mode == "off":
            return self.inner.complete(request)
        cached = self._load(request)
        if cached is not None:
            return cached
        if self.mode == "replay":
            self.misses += 1
            raise LLMError(
                "cassette_miss",
                f"no recording for {request.cache_key or 'request'}",
                retryable=False,
            )
        self.misses += 1
        response = self.inner.complete(request)
        self._save(request, response)
        return response

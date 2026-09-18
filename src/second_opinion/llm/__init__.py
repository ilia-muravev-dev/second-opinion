"""Model providers behind one protocol; the factory picks by settings."""

from __future__ import annotations

from pathlib import Path

from second_opinion.config import Settings
from second_opinion.llm.anthropic import AnthropicProvider
from second_opinion.llm.cassette import CassetteMode, CassetteProvider
from second_opinion.llm.fake import FakeProvider
from second_opinion.llm.openai_compat import OpenAICompatibleProvider
from second_opinion.llm.provider import LLMError, LLMProvider, LLMRequest, LLMResponse, LLMUsage


def make_provider(
    settings: Settings,
    *,
    cassette_dir: Path | None = None,
    cassette_mode: CassetteMode = "off",
) -> LLMProvider:
    inner: LLMProvider
    if settings.provider == "fake":
        inner = FakeProvider()
    elif settings.provider == "anthropic":
        inner = AnthropicProvider(settings.anthropic_api_key)
    else:
        inner = OpenAICompatibleProvider(settings.openai_base_url, settings.openai_api_key)
    if cassette_mode != "off" and cassette_dir is not None:
        return CassetteProvider(inner, cassette_dir, cassette_mode)
    return inner


__all__ = [
    "CassetteMode",
    "CassetteProvider",
    "FakeProvider",
    "LLMError",
    "LLMProvider",
    "LLMRequest",
    "LLMResponse",
    "LLMUsage",
    "make_provider",
]

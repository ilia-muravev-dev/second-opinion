"""Runtime settings, read once from the environment (and a local .env when present)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Provider = Literal["anthropic", "openai", "fake"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SO_", env_file=".env", extra="ignore")

    provider: Provider = "anthropic"
    model: str = "claude-haiku-4-5-20251001"
    prompt_version: str = "v1"
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    openai_base_url: str = "https://openrouter.ai/api/v1"
    # Review budgets — a pull request larger than this is reviewed in parts, or partly.
    max_request_tokens: int = Field(default=24_000, ge=2_000)
    max_pr_tokens: int = Field(default=120_000, ge=2_000)
    max_findings: int = Field(default=15, ge=1)
    min_confidence: float = Field(default=0.5, ge=0, le=1)
    # low | medium | high: thinking budget for models that reason
    effort: str = "low"
    github_token: str | None = None
    log_level: str = "info"


def load_settings(**overrides: object) -> Settings:
    return Settings(**overrides)  # type: ignore[arg-type]

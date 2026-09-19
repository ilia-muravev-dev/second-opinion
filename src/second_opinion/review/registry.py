"""Prompt versions live next to the code and are addressed by name in reports. A version names
the review prompt and, from v3 on, the verification prompt that gives every finding its second
opinion."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent / "prompts"


@dataclass(frozen=True)
class PromptConfig:
    name: str
    review: str
    verify: str | None


PROMPT_VERSIONS: dict[str, PromptConfig] = {
    "v1": PromptConfig("v1", review="v1", verify=None),
    "v2": PromptConfig("v2", review="v2", verify=None),
    "v3": PromptConfig("v3", review="v2", verify="v3-verify"),
}


def prompt_config(name: str) -> PromptConfig:
    try:
        return PROMPT_VERSIONS[name]
    except KeyError as error:
        msg = f"unknown prompt version {name!r}; available: {', '.join(PROMPT_VERSIONS)}"
        raise ValueError(msg) from error


def available_prompts() -> list[str]:
    return list(PROMPT_VERSIONS)


@cache
def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        msg = f"unknown prompt {name!r}; available: {', '.join(available_prompts())}"
        raise ValueError(msg)
    return path.read_text(encoding="utf-8").strip()

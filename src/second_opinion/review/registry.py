"""Prompt versions live next to the code and are addressed by name in reports."""

from __future__ import annotations

from functools import cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent / "prompts"


def available_prompts() -> list[str]:
    return sorted(p.stem for p in PROMPTS_DIR.glob("v*.md") if not p.stem.endswith("-verify"))


@cache
def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        msg = f"unknown prompt {name!r}; available: {', '.join(available_prompts())}"
        raise ValueError(msg)
    return path.read_text(encoding="utf-8").strip()

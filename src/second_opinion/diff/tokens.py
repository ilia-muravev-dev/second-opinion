"""A cheap token estimate. Budgets need to be roughly right, not exact, and a tokenizer for every
model is not worth a dependency: code averages a little under four characters per token."""

from __future__ import annotations

import math

CHARS_PER_TOKEN = 3.5


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)

"""Prices per million tokens for the models we price ourselves; other providers report cost."""

from __future__ import annotations

from second_opinion.llm.provider import LLMUsage

# input, cache write, cache read, output — USD per million tokens (anthropic.com/pricing, 2026-09)
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-haiku-4-5": (1.00, 1.25, 0.10, 5.00),
    "claude-sonnet-5": (2.00, 2.50, 0.20, 10.00),
    "claude-opus-5": (5.00, 6.25, 0.50, 25.00),
}


def price_for(model: str) -> tuple[float, float, float, float] | None:
    for prefix, prices in PRICES.items():
        if model.startswith(prefix):
            return prices
    return None


def cost_usd(model: str, usage: LLMUsage) -> float | None:
    prices = price_for(model)
    if prices is None:
        return None
    inp, write, read, out = prices
    return (
        usage.input_tokens * inp
        + usage.cache_write_tokens * write
        + usage.cache_read_tokens * read
        + usage.output_tokens * out
    ) / 1_000_000

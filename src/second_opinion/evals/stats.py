"""Confidence intervals for the proportions in the reports."""

from __future__ import annotations

import math


def wilson(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion; (0, 0) when there is nothing to count."""
    if total == 0:
        return (0.0, 0.0)
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return (max(0.0, centre - half), min(1.0, centre + half))


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def interval(successes: int, total: int) -> str:
    low, high = wilson(successes, total)
    return f"{pct(low)} to {pct(high)}"

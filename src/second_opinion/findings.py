"""One shape for everything the reviewer has to say, whether a regex or a model said it."""

from __future__ import annotations

import hashlib
import re
from typing import Literal

from pydantic import BaseModel, Field, computed_field

Severity = Literal["low", "medium", "high"]
Source = Literal["check", "model"]
Category = Literal[
    "security",
    "correctness",
    "concurrency",
    "error_handling",
    "data",
    "performance",
    "testing",
    "dependencies",
    "hygiene",
    "style",
]

SEVERITY_ORDER: dict[str, int] = {"high": 0, "medium": 1, "low": 2}


class Finding(BaseModel):
    source: Source
    file: str
    line: int | None = Field(default=None, description="New-side line; None means summary only")
    end_line: int | None = None
    severity: Severity
    category: Category
    title: str = Field(min_length=1, max_length=200)
    explanation: str
    suggestion: str | None = None
    confidence: float = Field(default=1.0, ge=0, le=1)
    check: str | None = Field(default=None, description="The deterministic check that fired")
    verdict: Literal["confirmed", "plausible", "rejected"] | None = None
    verdict_reason: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def fingerprint(self) -> str:
        """Stable across re-runs when the same thing is said about the same file: used to avoid
        posting an inline comment twice. The line is left out on purpose — it moves."""
        normalised = re.sub(r"[^a-z0-9]+", " ", self.title.lower()).strip()
        return hashlib.sha1(f"{self.file}\n{normalised}".encode()).hexdigest()[:12]  # noqa: S324

    @property
    def anchored(self) -> bool:
        return self.line is not None


def sort_findings(findings: list[Finding]) -> list[Finding]:
    return sorted(
        findings,
        key=lambda f: (SEVERITY_ORDER[f.severity], -f.confidence, f.file, f.line or 0),
    )

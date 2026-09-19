"""The contract between the prompt and the code: what a model review must return. Kept strict
(every property required, nothing extra) so both Anthropic's and OpenAI-style structured outputs
accept it; optional values are nullable, not absent."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from second_opinion.findings import Category, Severity

CATEGORIES: tuple[str, ...] = (
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
)


class ModelFinding(BaseModel):
    file: str
    line: int = Field(ge=1, description="New-side line number shown in the diff")
    end_line: int | None = None
    severity: Severity
    category: Category
    title: str = Field(min_length=1, max_length=200)
    explanation: str
    suggestion: str | None = None
    confidence: float = Field(ge=0, le=1)

    @field_validator("confidence", mode="before")
    @classmethod
    def percent_to_fraction(cls, value: object) -> object:
        """Models write 98 for 0.98 often enough to accept it."""
        if isinstance(value, int | float) and 1 < value <= 100:
            return value / 100
        return value

    @field_validator("severity", mode="before")
    @classmethod
    def lowercase_severity(cls, value: object) -> object:
        return value.lower() if isinstance(value, str) else value

    @field_validator("category", mode="before")
    @classmethod
    def normalise_category(cls, value: object) -> object:
        if isinstance(value, str):
            lowered = value.lower().replace("-", "_").replace(" ", "_")
            return {"bug": "correctness", "logic": "correctness", "error": "error_handling"}.get(
                lowered, lowered
            )
        return value


class ReviewOutput(BaseModel):
    findings: list[ModelFinding]
    summary: str = ""


REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["findings", "summary"],
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "file",
                    "line",
                    "end_line",
                    "severity",
                    "category",
                    "title",
                    "explanation",
                    "suggestion",
                    "confidence",
                ],
                "properties": {
                    "file": {"type": "string", "description": "Path exactly as shown in the diff"},
                    "line": {
                        "type": "integer",
                        "description": "The new-side line number printed before the line",
                    },
                    "end_line": {
                        "type": ["integer", "null"],
                        "description": "Last line of the range, or null for one line",
                    },
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                    "category": {"type": "string", "enum": list(CATEGORIES)},
                    "title": {"type": "string", "description": "One line, specific, no prefix"},
                    "explanation": {
                        "type": "string",
                        "description": "Why this is a problem, citing what the code does",
                    },
                    "suggestion": {
                        "type": ["string", "null"],
                        "description": "What to change, or null",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "0 to 1: how sure you are this is a real defect",
                    },
                },
            },
        },
        "summary": {
            "type": "string",
            "description": "Two or three sentences on what the change does and its risk",
        },
    },
}

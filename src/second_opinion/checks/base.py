"""A deterministic check looks at the diff and returns findings it is certain about."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from second_opinion.diff import Diff, DiffLine, FileDiff, FilteredDiff
from second_opinion.findings import Finding

TEST_PATH_MARKERS = ("/test/", "/tests/", "/__tests__/", "/e2e/", "/spec/")
TEST_NAME_MARKERS = (".test.", ".spec.", "_test.", "conftest")


@dataclass(frozen=True)
class CheckInput:
    reviewed: FilteredDiff
    full: Diff

    def reviewed_files(self) -> tuple[FileDiff, ...]:
        return self.reviewed.files


@dataclass(frozen=True)
class Check:
    id: str
    description: str
    run: Callable[[CheckInput], list[Finding]]


def is_test_path(path: str) -> bool:
    lowered = f"/{path.lower()}"
    name = lowered.rsplit("/", 1)[-1]
    return (
        any(marker in lowered for marker in TEST_PATH_MARKERS)
        or any(marker in name for marker in TEST_NAME_MARKERS)
        or name.startswith("test_")
    )


def added_lines(file: FileDiff) -> Iterator[DiffLine]:
    yield from file.added


def finding(
    check: str,
    file: FileDiff | str,
    line: int | None,
    *,
    severity: str,
    category: str,
    title: str,
    explanation: str,
    suggestion: str | None = None,
) -> Finding:
    return Finding.model_validate(
        {
            "source": "check",
            "check": check,
            "file": file if isinstance(file, str) else file.path,
            "line": line,
            "severity": severity,
            "category": category,
            "title": title,
            "explanation": explanation,
            "suggestion": suggestion,
            "confidence": 1.0,
        }
    )

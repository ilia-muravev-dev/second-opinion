"""The deterministic layer: checks that are certain, cheap, and run before any model."""

from __future__ import annotations

from second_opinion.checks import (
    debug_statements,
    dependencies,
    files,
    markers,
    secrets,
    skipped_tests,
)
from second_opinion.checks.base import Check, CheckInput
from second_opinion.diff import Diff, FilteredDiff
from second_opinion.findings import Finding, sort_findings

CHECKS: tuple[Check, ...] = (
    secrets.CHECK,
    debug_statements.CHECK,
    skipped_tests.CHECK,
    markers.CHECK,
    dependencies.CHECK,
    files.CHECK,
)


def run_checks(reviewed: FilteredDiff, full: Diff, only: set[str] | None = None) -> list[Finding]:
    inputs = CheckInput(reviewed=reviewed, full=full)
    out: list[Finding] = []
    for check in CHECKS:
        if only is not None and check.id not in only:
            continue
        out.extend(check.run(inputs))
    return sort_findings(out)


__all__ = ["CHECKS", "Check", "CheckInput", "run_checks"]

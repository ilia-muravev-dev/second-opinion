"""Tests switched off or focused: `.skip`, `.only`, `xit`, `pytest.mark.skip`."""

from __future__ import annotations

import re

from second_opinion.checks.base import Check, CheckInput, finding
from second_opinion.findings import Finding

FOCUSED = re.compile(r"\b(?:it|test|describe)\.only\(|\bf(?:it|describe)\(")
SKIPPED = re.compile(
    r"\b(?:it|test|describe)\.skip\(|\bx(?:it|test|describe)\(|"
    r"@pytest\.mark\.skip|pytest\.skip\(|@unittest\.skip|@skip\("
)


def run(inputs: CheckInput) -> list[Finding]:
    out: list[Finding] = []
    for file in inputs.reviewed_files():
        for line in file.added:
            if FOCUSED.search(line.content):
                out.append(
                    finding(
                        "skipped_tests",
                        file,
                        line.new_no,
                        severity="high",
                        category="testing",
                        title="A focused test (.only) disables the rest of the suite",
                        explanation=(
                            "With `.only` left in, CI runs this test and skips every other."
                        ),
                        suggestion="Remove `.only`.",
                    )
                )
            elif SKIPPED.search(line.content):
                out.append(
                    finding(
                        "skipped_tests",
                        file,
                        line.new_no,
                        severity="medium",
                        category="testing",
                        title="A test is being skipped",
                        explanation=(
                            "A skipped test protects nothing; the reason should be in the PR."
                        ),
                        suggestion=(
                            "Fix or delete the test, or say why it is skipped and until when."
                        ),
                    )
                )
    return out


CHECK = Check("skipped_tests", "Skipped or focused tests", run)

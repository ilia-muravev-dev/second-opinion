"""Whole-file signals: an applied migration edited, an environment file committed, a pull
request too large to review well, source changed with no test touched."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from second_opinion.checks.base import Check, CheckInput, finding, is_test_path
from second_opinion.findings import Finding

MIGRATION_PATH = re.compile(
    r"(?:^|/)(?:migrations|alembic/versions|db/migrate)/(?:[^/]+/)?[^/]+\.(?:sql|py|ts|js|rb)$"
)
ENV_FILE = re.compile(r"(?:^|/)\.env(?:\.[A-Za-z0-9_-]+)?$")
ENV_TEMPLATE = re.compile(r"\.env\.(?:example|sample|template|dist|defaults?)$")
CODE_LANGUAGES = {"python", "typescript", "javascript"}
LARGE_PR_LINES = 1500
UNTESTED_SOURCE_LINES = 40


def run(inputs: CheckInput) -> list[Finding]:
    out: list[Finding] = []
    for file in inputs.full.files:
        if MIGRATION_PATH.search(file.path) and file.status == "modified":
            out.append(
                finding(
                    "files",
                    file,
                    file.hunks[0].lines[0].new_no if file.hunks and file.hunks[0].lines else None,
                    severity="high",
                    category="data",
                    title="An existing migration was edited",
                    explanation=(
                        "Migrations that already ran somewhere will not run again; editing one "
                        "leaves environments that applied it out of step with the schema."
                    ),
                    suggestion="Add a new migration instead.",
                )
            )
        name = PurePosixPath(file.path).name
        if (
            ENV_FILE.search(file.path)
            and not ENV_TEMPLATE.search(name)
            and file.status != "deleted"
        ):
            out.append(
                finding(
                    "files",
                    file,
                    None,
                    severity="high",
                    category="security",
                    title=f"{name} committed",
                    explanation="Environment files hold real configuration and usually secrets.",
                    suggestion=(
                        "Remove it from the repository, add it to .gitignore, keep a .env.example."
                    ),
                )
            )
    total = inputs.reviewed.diff.changed_lines
    if total > LARGE_PR_LINES:
        out.append(
            finding(
                "files",
                "",
                None,
                severity="low",
                category="hygiene",
                title=f"Large pull request ({total} changed lines after filters)",
                explanation="Review quality drops with size; defects hide in big diffs.",
                suggestion="Split it, if the pieces can stand alone.",
            )
        )
    source_lines = sum(
        f.changed_lines
        for f in inputs.reviewed.files
        if f.language in CODE_LANGUAGES and not is_test_path(f.path)
    )
    tests_touched = any(is_test_path(f.path) for f in inputs.full.files)
    if source_lines >= UNTESTED_SOURCE_LINES and not tests_touched:
        out.append(
            finding(
                "files",
                "",
                None,
                severity="low",
                category="testing",
                title="Source changed, no test changed",
                explanation=(
                    f"{source_lines} lines of source changed and no test file is part of the "
                    "pull request."
                ),
                suggestion="Add or update a test, or say why none applies.",
            )
        )
    return out


CHECK = Check("files", "Migration edits, env files, PR size, untested source", run)

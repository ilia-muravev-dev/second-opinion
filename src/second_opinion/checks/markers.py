"""Small signs of unfinished work: TODO/FIXME markers, lint suppressions, merge-conflict markers."""

from __future__ import annotations

import re

from second_opinion.checks.base import Check, CheckInput, finding
from second_opinion.findings import Finding

TODO = re.compile(r"\b(?:TODO|FIXME|XXX|HACK)\b")
SUPPRESSION = re.compile(
    r"eslint-disable|biome-ignore|@ts-ignore|@ts-expect-error|#\s*noqa|#\s*type:\s*ignore|"
    r"#\s*pragma:\s*no cover|# nosec"
)
CONFLICT = re.compile(r"^(?:<{7}|>{7}|={7})(?:\s|$)")


def run(inputs: CheckInput) -> list[Finding]:
    out: list[Finding] = []
    reviewed = {f.path for f in inputs.reviewed_files()}
    for file in inputs.full.files:
        for line in file.added:
            text = line.content
            if file.path not in reviewed and not CONFLICT.match(text):
                continue  # generated code is full of suppressions and TODOs that are not ours
            if CONFLICT.match(text):
                out.append(
                    finding(
                        "markers",
                        file,
                        line.new_no,
                        severity="high",
                        category="correctness",
                        title="Merge conflict marker committed",
                        explanation="This line is a conflict marker, not code.",
                        suggestion="Resolve the conflict and remove the markers.",
                    )
                )
            elif TODO.search(text):
                out.append(
                    finding(
                        "markers",
                        file,
                        line.new_no,
                        severity="low",
                        category="hygiene",
                        title="TODO/FIXME added",
                        explanation="A marker without an issue link tends to stay forever.",
                        suggestion="Link an issue, or do it in this PR.",
                    )
                )
            elif SUPPRESSION.search(text):
                out.append(
                    finding(
                        "markers",
                        file,
                        line.new_no,
                        severity="medium" if "ts-ignore" in text else "low",
                        category="hygiene",
                        title="Lint or type check suppressed",
                        explanation="A suppression hides a diagnostic; it should say why.",
                        suggestion="Fix the diagnostic, or add the reason next to the suppression.",
                    )
                )
    return out


CHECK = Check("markers", "TODO markers, suppressions, conflict markers", run)

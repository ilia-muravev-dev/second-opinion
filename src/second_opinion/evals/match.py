"""Did the reviewer find the planted defect? A finding hits a label when it names the same file
and points within a few lines of it. One finding can hit one label; one label counts once."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from second_opinion.evals.mutate import Label
from second_opinion.findings import Finding

LINE_TOLERANCE = 3


def hits(finding: Finding, label: Label, tolerance: int = LINE_TOLERANCE) -> bool:
    if finding.file != label.file or finding.line is None:
        return False
    start = finding.line
    end = finding.end_line if finding.end_line is not None and finding.end_line >= start else start
    return start - tolerance <= label.line <= end + tolerance


@dataclass
class CaseScore:
    case_id: str
    kind: str
    labels: int
    found: int
    model_findings: int
    model_hits: int
    check_findings: int
    check_hits: int
    unlabelled_model: int
    category_agreed: int
    found_by: list[dict[str, Any]] = field(default_factory=list)


def score_case(case_id: str, kind: str, labels: list[Label], findings: list[Finding]) -> CaseScore:
    remaining = list(labels)
    model = [f for f in findings if f.source == "model"]
    checks = [f for f in findings if f.source == "check"]
    model_hits = check_hits = agreed = 0
    found_by: list[dict[str, Any]] = []
    for finding in findings:
        label = next((label for label in remaining if hits(finding, label)), None)
        if label is None:
            continue
        remaining.remove(label)
        if finding.source == "model":
            model_hits += 1
        else:
            check_hits += 1
        if finding.category == label.category:
            agreed += 1
        found_by.append(
            {
                "operator": label.operator,
                "source": finding.source,
                "title": finding.title,
                "line": finding.line,
                "label_line": label.line,
            }
        )
    return CaseScore(
        case_id=case_id,
        kind=kind,
        labels=len(labels),
        found=len(labels) - len(remaining),
        model_findings=len(model),
        model_hits=model_hits,
        check_findings=len(checks),
        check_hits=check_hits,
        unlabelled_model=len(model) - model_hits,
        category_agreed=agreed,
        found_by=found_by,
    )

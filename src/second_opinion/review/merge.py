"""From raw model output to findings worth posting: valid anchors, one finding per thing said,
a confidence floor, a cap on how many — and what was dropped, so the report can say."""

from __future__ import annotations

from dataclasses import dataclass, field

from second_opinion.diff import Diff
from second_opinion.findings import Finding, sort_findings
from second_opinion.review.schema import ModelFinding


@dataclass
class MergeStats:
    received: int = 0
    unanchored: int = 0
    unknown_file: int = 0
    duplicates: int = 0
    below_confidence: int = 0
    over_cap: int = 0
    notes: list[str] = field(default_factory=list)


def to_finding(raw: ModelFinding, diff: Diff, stats: MergeStats) -> Finding | None:
    """A model finding becomes a Finding when its file is in the diff; a line the diff does not
    show is dropped from the anchor (summary only), never posted on the wrong line."""
    file = diff.file(raw.file)
    if file is None:
        stats.unknown_file += 1
        stats.notes.append(f"dropped a finding on {raw.file!r}: not in the diff ({raw.title})")
        return None
    line: int | None = raw.line
    end_line = raw.end_line
    if line is not None and not file.covers_new_line(line):
        stats.unanchored += 1
        stats.notes.append(f"{raw.file}:{raw.line} is not in the diff; kept for the summary only")
        line, end_line = None, None
    if (
        end_line is not None
        and line is not None
        and (end_line < line or not file.covers_new_line(end_line))
    ):
        end_line = None
    return Finding(
        source="model",
        file=raw.file,
        line=line,
        end_line=end_line,
        severity=raw.severity,
        category=raw.category,
        title=raw.title.strip(),
        explanation=raw.explanation.strip(),
        suggestion=(raw.suggestion or "").strip() or None,
        confidence=raw.confidence,
        hunk_range=hunk_range,
    )


def merge_findings(
    raw: list[ModelFinding],
    diff: Diff,
    *,
    min_confidence: float,
    max_findings: int,
    stats: MergeStats | None = None,
) -> tuple[list[Finding], MergeStats]:
    stats = stats or MergeStats()
    stats.received += len(raw)
    by_fingerprint: dict[str, Finding] = {}
    for item in raw:
        finding = to_finding(item, diff, stats)
        if finding is None:
            continue
        if finding.confidence < min_confidence:
            stats.below_confidence += 1
            continue
        existing = by_fingerprint.get(finding.fingerprint)
        if existing is not None:
            stats.duplicates += 1
            if finding.confidence > existing.confidence:
                by_fingerprint[finding.fingerprint] = finding
            continue
        by_fingerprint[finding.fingerprint] = finding
    ordered = sort_findings(list(by_fingerprint.values()))
    if len(ordered) > max_findings:
        stats.over_cap = len(ordered) - max_findings
        ordered = ordered[:max_findings]
    return ordered, stats

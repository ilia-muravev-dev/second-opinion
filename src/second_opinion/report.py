"""The summary a reviewer leaves: what was found, what was skipped, what it cost."""

from __future__ import annotations

from dataclasses import dataclass, field

from second_opinion.diff import SkippedFile
from second_opinion.findings import Finding, sort_findings
from second_opinion.llm.provider import LLMUsage

MARKER = "<!-- second-opinion -->"


@dataclass
class ReviewReport:
    findings: list[Finding]
    summaries: list[str] = field(default_factory=list)
    skipped: list[SkippedFile] = field(default_factory=list)
    model: str = ""
    provider: str = ""
    prompt_version: str = ""
    requests: int = 0
    usage: LLMUsage = field(default_factory=LLMUsage)
    cost_usd: float | None = None
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    verified: bool = False
    rejected: int = 0

    @property
    def check_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.source == "check"]

    @property
    def model_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.source == "model"]


SEVERITY_ICON = {"high": "🔴", "medium": "🟠", "low": "🟡"}


def where(f: Finding) -> str:
    if f.line is None:
        return f"`{f.file}`" if f.file else "pull request"
    span = f"{f.line}" if not f.end_line or f.end_line == f.line else f"{f.line}-{f.end_line}"
    return f"`{f.file}:{span}`"


def render_findings(findings: list[Finding]) -> list[str]:
    if not findings:
        return ["No findings. ✅"]
    counts = {s: sum(1 for f in findings if f.severity == s) for s in ("high", "medium", "low")}
    lines = [
        f"**{len(findings)} finding(s)** — "
        + ", ".join(f"{n} {s}" for s, n in counts.items() if n)
        + ".",
        "",
        "| | Where | Finding | Source | Confidence |",
        "| --- | --- | --- | --- | --- |",
    ]
    for f in findings:
        source = f"check: {f.check}" if f.source == "check" else "model"
        if f.verdict:
            source += f" · {f.verdict}"
        lines.append(
            f"| {SEVERITY_ICON[f.severity]} | {where(f)} | **{f.title}** | {source} | "
            f"{f.confidence:.0%} |"
        )
    lines.append("")
    for f in findings:
        if f.line is None or f.source != "model":  # anchored model findings carry their text inline
            lines.extend(render_details(f))
    lines.append("")
    return lines


def render_details(f: Finding) -> list[str]:
    lines = [
        f"<details><summary>{SEVERITY_ICON[f.severity]} {f.title} — {where(f)}</summary>",
        "",
        f.explanation,
    ]
    if f.suggestion:
        lines += ["", f"**Suggestion:** {f.suggestion}"]
    lines += ["", "</details>"]
    return lines


def render_meta(report: ReviewReport) -> str:
    meta = [f"{report.provider}/{report.model}" if report.provider else report.model]
    if report.prompt_version:
        meta.append(f"prompt {report.prompt_version}")
    if report.verified:
        meta.append(f"second opinion: {report.rejected} rejected")
    meta.append(f"{report.requests} request(s)")
    cached = (
        f" ({report.usage.cache_read_tokens:,} cached)" if report.usage.cache_read_tokens else ""
    )
    meta.append(
        f"{report.usage.total_input:,} in / {report.usage.output_tokens:,} out tokens{cached}"
    )
    if report.cost_usd is not None:
        meta.append(f"${report.cost_usd:.4f}")
    return "<sub>" + " · ".join(meta) + "</sub>"


def render_markdown(report: ReviewReport) -> str:
    lines: list[str] = [MARKER, "## Second opinion", ""]
    if report.summaries:
        lines += [" ".join(report.summaries), ""]
    lines.extend(render_findings(sort_findings(report.findings)))
    if report.skipped:
        shown = ", ".join(f"`{s.path}` ({s.reason})" for s in report.skipped[:12])
        more = f" and {len(report.skipped) - 12} more" if len(report.skipped) > 12 else ""
        lines += [f"Not reviewed: {shown}{more}.", ""]
    if report.errors:
        lines += ["Problems during the review: " + "; ".join(report.errors), ""]
    lines.append(render_meta(report))
    return "\n".join(lines) + "\n"


def render_inline_comment(f: Finding) -> str:
    body = f"{SEVERITY_ICON[f.severity]} **{f.title}**\n\n{f.explanation}"
    if f.suggestion:
        body += f"\n\n**Suggestion:** {f.suggestion}"
    source = (
        f"check: {f.check}"
        if f.source == "check"
        else f"{f.category}, confidence {f.confidence:.0%}"
    )
    if f.verdict:
        source += f", {f.verdict}"
    return f"{body}\n\n<sub>second-opinion · {source}</sub>"

"""One review, end to end: parse, filter, checks, model pass, report. The CLI, the action and the
eval runner all go through here so they cannot disagree about what a review is."""

from __future__ import annotations

from dataclasses import dataclass

from second_opinion.checks import run_checks
from second_opinion.config import Settings
from second_opinion.diff import Diff, FilteredDiff, filter_diff, parse_diff
from second_opinion.findings import Finding, sort_findings
from second_opinion.llm.provider import LLMProvider, LLMUsage
from second_opinion.report import ReviewReport
from second_opinion.review import ReviewContext, ReviewResult, review_diff


@dataclass
class ReviewRun:
    report: ReviewReport
    full: Diff
    reviewed: FilteredDiff
    model_result: ReviewResult | None


def run_review(
    diff_text: str,
    settings: Settings,
    provider: LLMProvider | None,
    *,
    title: str | None = None,
    description: str | None = None,
    case_id: str | None = None,
    checks_only: bool = False,
) -> ReviewRun:
    full = parse_diff(diff_text)
    reviewed = filter_diff(full)
    findings: list[Finding] = run_checks(reviewed, full)
    context = ReviewContext(title=title, description=description, check_findings=list(findings))
    result: ReviewResult | None = None
    if provider is not None and not checks_only and reviewed.files:
        result = review_diff(
            reviewed.diff,
            provider,
            model=settings.model,
            prompt_version=settings.prompt_version,
            context=context,
            max_request_tokens=settings.max_request_tokens,
            min_confidence=settings.min_confidence,
            max_findings=settings.max_findings,
            case_id=case_id,
        )
        findings = sort_findings(findings + result.findings)
    report = ReviewReport(
        findings=findings,
        summaries=result.summaries if result else [],
        skipped=list(reviewed.skipped),
        model=settings.model if result else "",
        provider=provider.name if (provider and result) else "",
        prompt_version=settings.prompt_version if result else "",
        requests=result.requests if result else 0,
        usage=result.usage if result else LLMUsage(),
        cost_usd=result.cost_usd if result else None,
        notes=list(result.stats.notes) if result else [],
        errors=list(result.errors) if result else [],
    )
    return ReviewRun(report=report, full=full, reviewed=reviewed, model_result=result)

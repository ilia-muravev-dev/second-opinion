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
from second_opinion.review import (
    ReviewContext,
    ReviewResult,
    VerifyResult,
    prompt_config,
    review_diff,
    verify_findings,
)


@dataclass
class ReviewRun:
    report: ReviewReport
    full: Diff
    reviewed: FilteredDiff
    model_result: ReviewResult | None
    verify_result: VerifyResult | None = None


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
            effort=settings.effort,
        )
        findings = sort_findings(findings + result.findings)
    verified: VerifyResult | None = None
    config = prompt_config(settings.prompt_version)
    if result is not None and provider is not None and config.verify and result.findings:
        verified = verify_findings(
            findings,
            reviewed.diff,
            provider,
            model=settings.model,
            prompt_name=config.verify,
            case_id=case_id,
            effort=settings.effort,
        )
        findings = sort_findings(verified.kept)
    usage = LLMUsage()
    requests = 0
    cost: float | None = None
    errors: list[str] = []
    notes: list[str] = []
    if result is not None:
        usage, requests, cost = result.usage, result.requests, result.cost_usd
        errors, notes = list(result.errors), list(result.stats.notes)
    if verified is not None:
        usage = usage + verified.usage
        requests += verified.requests
        cost = None if cost is None or verified.cost_usd is None else cost + verified.cost_usd
        errors += verified.errors
        notes += [
            f"second opinion rejected: {f.file}:{f.line} {f.title} — {f.verdict_reason}"
            for f in verified.rejected
        ]
        if verified.unverified:
            notes.append(f"{verified.unverified} finding(s) posted unverified")
    report = ReviewReport(
        findings=findings,
        summaries=result.summaries if result else [],
        skipped=list(reviewed.skipped),
        model=settings.model if result else "",
        provider=provider.name if (provider and result) else "",
        prompt_version=settings.prompt_version if result else "",
        requests=requests,
        usage=usage,
        cost_usd=cost,
        notes=notes,
        errors=errors,
        verified=verified is not None,
        rejected=len(verified.rejected) if verified else 0,
    )
    return ReviewRun(
        report=report,
        full=full,
        reviewed=reviewed,
        model_result=result,
        verify_result=verified,
    )

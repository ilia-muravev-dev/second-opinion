"""Turning a report into what lands on the pull request: inline comments for anchored findings
not posted before, one summary comment updated in place. Inline posting falls back to the summary
when GitHub refuses the anchors, so a review is never lost to a 422."""

from __future__ import annotations

from dataclasses import dataclass, field

from second_opinion.findings import Finding
from second_opinion.github.client import (
    FINGERPRINT_TAG,
    GitHubClient,
    GitHubError,
    InlineComment,
    PullRequest,
)
from second_opinion.report import ReviewReport, render_inline_comment, render_markdown


@dataclass
class PostOutcome:
    inline_posted: int = 0
    inline_skipped_seen: int = 0
    inline_fell_back: bool = False
    summary_updated: bool = False
    notes: list[str] = field(default_factory=list)


def inline_comment_for(f: Finding) -> InlineComment | None:
    if f.line is None:
        return None
    # A range is (start_line, line) on GitHub; the finding's line is the start of its range.
    end = f.end_line if f.end_line is not None and f.end_line > f.line else None
    return InlineComment(
        path=f.file,
        line=end if end is not None else f.line,
        start_line=f.line if end is not None else None,
        body=render_inline_comment(f) + "\n" + FINGERPRINT_TAG.format(fingerprint=f.fingerprint),
    )


def post_review(
    client: GitHubClient, pr: PullRequest, report: ReviewReport, *, mode: str
) -> PostOutcome:
    """`mode`: `review` (inline + summary), `summary` (summary only), `none`."""
    outcome = PostOutcome()
    if mode == "none":
        return outcome
    if mode == "review":
        seen = client.existing_fingerprints(pr.owner, pr.repo, pr.number)
        comments: list[InlineComment] = []
        for f in report.findings:
            comment = inline_comment_for(f)
            if comment is None:
                continue
            if f.fingerprint in seen:
                outcome.inline_skipped_seen += 1
                continue
            comments.append(comment)
        if comments:
            body = f"second-opinion left {len(comments)} inline comment(s); the summary is below."
            try:
                client.create_review(pr, body=body, comments=comments)
                outcome.inline_posted = len(comments)
            except GitHubError as error:
                if error.status != 422:
                    raise
                outcome.inline_fell_back = True
                outcome.notes.append(
                    f"GitHub refused the inline anchors ({error}); findings are in the summary only"
                )
    summary = render_markdown(report)
    if outcome.notes:
        summary = summary.replace("<sub>", "\n".join(outcome.notes) + "\n\n<sub>", 1)
    client.upsert_summary(pr, summary)
    outcome.summary_updated = True
    return outcome

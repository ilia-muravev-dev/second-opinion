"""The model layer of the review: prompts, the output contract, the pass over the diff."""

from second_opinion.review.merge import MergeStats, merge_findings
from second_opinion.review.registry import available_prompts, load_prompt
from second_opinion.review.reviewer import ReviewContext, ReviewResult, review_diff
from second_opinion.review.schema import REVIEW_SCHEMA, ModelFinding, ReviewOutput

__all__ = [
    "REVIEW_SCHEMA",
    "MergeStats",
    "ModelFinding",
    "ReviewContext",
    "ReviewOutput",
    "ReviewResult",
    "available_prompts",
    "load_prompt",
    "merge_findings",
    "review_diff",
]

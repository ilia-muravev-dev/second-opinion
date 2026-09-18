"""The model layer of the review: prompts, the output contract, the pass over the diff."""

from second_opinion.review.merge import MergeStats, merge_findings
from second_opinion.review.registry import (
    PromptConfig,
    available_prompts,
    load_prompt,
    prompt_config,
)
from second_opinion.review.reviewer import ReviewContext, ReviewResult, review_diff
from second_opinion.review.schema import REVIEW_SCHEMA, ModelFinding, ReviewOutput
from second_opinion.review.verifier import VerifyResult, verify_findings

__all__ = [
    "REVIEW_SCHEMA",
    "MergeStats",
    "ModelFinding",
    "PromptConfig",
    "ReviewContext",
    "ReviewOutput",
    "ReviewResult",
    "VerifyResult",
    "available_prompts",
    "load_prompt",
    "merge_findings",
    "prompt_config",
    "review_diff",
    "verify_findings",
]

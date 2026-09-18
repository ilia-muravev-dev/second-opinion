"""The model pass: one request per chunk, structured output, validated against the diff."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from pydantic import ValidationError

from second_opinion.diff import Chunk, Diff, chunk_diff
from second_opinion.findings import Finding
from second_opinion.llm.pricing import cost_usd
from second_opinion.llm.provider import LLMError, LLMProvider, LLMRequest, LLMUsage
from second_opinion.review.merge import MergeStats, merge_findings
from second_opinion.review.registry import load_prompt
from second_opinion.review.schema import REVIEW_SCHEMA, ModelFinding, ReviewOutput


@dataclass
class ReviewContext:
    """What the model is told besides the diff."""

    title: str | None = None
    description: str | None = None
    check_findings: list[Finding] = field(default_factory=list)


@dataclass
class ReviewResult:
    findings: list[Finding]
    summaries: list[str]
    usage: LLMUsage
    requests: int
    cost_usd: float | None
    stats: MergeStats
    errors: list[str] = field(default_factory=list)
    chunks: int = 0


def build_user_message(chunk: Chunk, context: ReviewContext, prompt_version: str) -> str:
    parts: list[str] = []
    if context.title:
        parts.append(f"Pull request: {context.title}")
    if context.description:
        parts.append(f"Description:\n{context.description.strip()}")
    if prompt_version != "v1" and context.check_findings:
        listed = "\n".join(
            f"- {f.file}:{f.line or '-'} — {f.title}" for f in context.check_findings[:30]
        )
        parts.append("Deterministic checks already reported these; do not repeat them:\n" + listed)
    if chunk.total > 1:
        parts.append(
            f"Diff part {chunk.index} of {chunk.total} (files are complete within a part)."
        )
    if chunk.truncated_files:
        parts.append("Over the review budget, shown partially: " + ", ".join(chunk.truncated_files))
    parts.append("```diff\n" + chunk.text + "\n```")
    return "\n\n".join(parts)


def parse_output(text: str) -> ReviewOutput:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        msg = f"the model did not return JSON: {error}"
        raise ValueError(msg) from error
    if isinstance(data, list):  # some models answer with the findings array alone
        data = {"findings": data, "summary": ""}
    try:
        return ReviewOutput.model_validate(data)
    except ValidationError as error:
        # keep the valid findings, drop the malformed ones
        findings: list[ModelFinding] = []
        for item in data.get("findings", []) if isinstance(data, dict) else []:
            try:
                findings.append(ModelFinding.model_validate(item))
            except ValidationError:
                continue
        if not findings and (not isinstance(data, dict) or data.get("findings")):
            msg = f"the model's answer does not match the schema: {error.errors()[:2]}"
            raise ValueError(msg) from error
        summary = str(data.get("summary", "")) if isinstance(data, dict) else ""
        return ReviewOutput(findings=findings, summary=summary)


def review_diff(
    diff: Diff,
    provider: LLMProvider,
    *,
    model: str,
    prompt_version: str,
    context: ReviewContext | None = None,
    max_request_tokens: int,
    min_confidence: float,
    max_findings: int,
    case_id: str | None = None,
    effort: str = "none",
) -> ReviewResult:
    context = context or ReviewContext()
    system = load_prompt(prompt_version)
    chunks = chunk_diff(diff, max_request_tokens)
    raw: list[ModelFinding] = []
    summaries: list[str] = []
    usage = LLMUsage()
    errors: list[str] = []
    reported_cost: float | None = 0.0
    requests = 0
    for chunk in chunks:
        request = LLMRequest(
            model=model,
            system=system,
            user=build_user_message(chunk, context, prompt_version),
            output_schema=REVIEW_SCHEMA,
            max_tokens=16384,
            effort=effort,
            cache_key=(
                {"case": case_id, "prompt": prompt_version, "chunk": f"{chunk.index}/{chunk.total}"}
                if case_id
                else {}
            ),
        )
        requests += 1
        try:
            response = provider.complete(request)
        except LLMError as error:
            errors.append(f"part {chunk.index}/{chunk.total}: {error}")
            if error.kind in {"rate_limit", "auth", "cassette_miss"}:
                raise  # nothing else will succeed either; the caller decides what to do
            continue
        usage = usage + response.usage
        if response.cost_usd is None:
            reported_cost = None
        elif reported_cost is not None:
            reported_cost += response.cost_usd
        if response.truncated:
            errors.append(f"part {chunk.index}/{chunk.total}: answer cut off at max_tokens")
        try:
            output = parse_output(response.text)
        except ValueError as error:
            errors.append(f"part {chunk.index}/{chunk.total}: {error}")
            continue
        raw.extend(output.findings)
        if output.summary.strip():
            summaries.append(output.summary.strip())
    findings, stats = merge_findings(
        raw, diff, min_confidence=min_confidence, max_findings=max_findings
    )
    priced = cost_usd(model, usage)
    return ReviewResult(
        findings=findings,
        summaries=summaries,
        usage=usage,
        requests=requests,
        cost_usd=priced if priced is not None else reported_cost,
        stats=stats,
        errors=errors,
        chunks=len(chunks),
    )

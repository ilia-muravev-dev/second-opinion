"""The second opinion: every model finding goes back to the model with the code it is about and
the question "is this real?". Rejections are dropped (and remembered); the rest are posted with
their verdict. If the verifier itself fails, the findings stay — unverified, and said so."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from second_opinion.diff import Diff
from second_opinion.diff.chunk import render_hunk
from second_opinion.findings import Finding
from second_opinion.llm.provider import LLMError, LLMProvider, LLMRequest, LLMUsage
from second_opinion.review.registry import load_prompt

VERIFY_BATCH = 10

VERIFY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdicts"],
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "verdict", "reason"],
                "properties": {
                    "id": {"type": "integer"},
                    "verdict": {"type": "string", "enum": ["confirmed", "plausible", "rejected"]},
                    "reason": {"type": "string"},
                },
            },
        }
    },
}


class Verdict(BaseModel):
    id: int
    verdict: str
    reason: str


class VerifyOutput(BaseModel):
    verdicts: list[Verdict]


@dataclass
class VerifyResult:
    kept: list[Finding]
    rejected: list[Finding]
    usage: LLMUsage = field(default_factory=LLMUsage)
    requests: int = 0
    cost_usd: float | None = 0.0
    errors: list[str] = field(default_factory=list)
    unverified: int = 0


def context_for(finding: Finding, diff: Diff) -> str:
    file = diff.file(finding.file)
    if file is None or finding.line is None:
        return "(no diff context available)"
    for hunk in file.hunks:
        if hunk.new_start <= finding.line <= hunk.new_end:
            return f"### {file.path}\n{render_hunk(hunk)}"
    return f"### {file.path}\n(line {finding.line} is outside the shown hunks)"


def build_verify_message(batch: list[tuple[int, Finding]], diff: Diff) -> str:
    parts: list[str] = []
    for index, finding in batch:
        parts.append(
            f"## Finding {index}\n"
            f"File: {finding.file}, line {finding.line}\n"
            f"Title: {finding.title}\n"
            f"Claim: {finding.explanation}\n"
            + (f"Suggested change: {finding.suggestion}\n" if finding.suggestion else "")
            + f"Reviewer confidence: {finding.confidence:.0%}\n\n"
            f"```diff\n{context_for(finding, diff)}\n```"
        )
    return "\n\n".join(parts)


def parse_verdicts(text: str) -> dict[int, Verdict]:
    data = json.loads(text)
    if isinstance(data, list):
        data = {"verdicts": data}
    try:
        output = VerifyOutput.model_validate(data)
    except ValidationError as error:
        msg = f"the verifier's answer does not match the schema: {error.errors()[:2]}"
        raise ValueError(msg) from error
    return {v.id: v for v in output.verdicts}


def verify_findings(
    findings: list[Finding],
    diff: Diff,
    provider: LLMProvider,
    *,
    model: str,
    prompt_name: str = "v3-verify",
    case_id: str | None = None,
    effort: str = "none",
) -> VerifyResult:
    result = VerifyResult(kept=[], rejected=[])
    to_verify = [f for f in findings if f.source == "model"]
    result.kept.extend(f for f in findings if f.source != "model")
    system = load_prompt(prompt_name)
    batches = [
        list(enumerate(to_verify, start=1))[i : i + VERIFY_BATCH]
        for i in range(0, len(to_verify), VERIFY_BATCH)
    ]
    for number, batch in enumerate(batches, start=1):
        request = LLMRequest(
            model=model,
            system=system,
            user=build_verify_message(batch, diff),
            output_schema=VERIFY_SCHEMA,
            max_tokens=8192,
            effort=effort,
            cache_key=(
                {"case": case_id, "prompt": prompt_name, "verify": f"{number}/{len(batches)}"}
                if case_id
                else {}
            ),
        )
        result.requests += 1
        try:
            response = provider.complete(request)
            verdicts = parse_verdicts(response.text)
        except LLMError as error:
            if error.kind in {"rate_limit", "auth", "cassette_miss"}:
                raise
            result.errors.append(f"verify {number}/{len(batches)}: {error}")
            result.kept.extend(f for _, f in batch)
            result.unverified += len(batch)
            continue
        except ValueError as error:
            result.errors.append(f"verify {number}/{len(batches)}: {error}")
            result.kept.extend(f for _, f in batch)
            result.unverified += len(batch)
            continue
        result.usage = result.usage + response.usage
        if response.cost_usd is None:
            result.cost_usd = None
        elif result.cost_usd is not None:
            result.cost_usd += response.cost_usd
        for index, finding in batch:
            verdict = verdicts.get(index)
            if verdict is None:
                result.kept.append(finding)
                result.unverified += 1
                continue
            judged = finding.model_copy(
                update={"verdict": verdict.verdict, "verdict_reason": verdict.reason.strip()}
            )
            if verdict.verdict == "rejected":
                result.rejected.append(judged)
            else:
                result.kept.append(judged)
    return result

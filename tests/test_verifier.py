import pytest

from second_opinion.config import load_settings
from second_opinion.llm import FakeProvider, LLMError
from second_opinion.pipeline import run_review
from second_opinion.report import render_markdown
from second_opinion.review import available_prompts, load_prompt, prompt_config
from second_opinion.review.verifier import VERIFY_SCHEMA

from .helpers import make_diff

DIFF = make_diff(
    {
        "src/booking.ts": (
            "export function reserve(count: number, capacity: number) {\n"
            "  if (count < capacity) {\n    return insert();\n  }\n  throw new NoCapacity();\n}\n",
            "export function reserve(count: number, capacity: number) {\n"
            "  if (count <= capacity) {\n    return insert();\n  }\n  throw new NoCapacity();\n}\n",
        )
    }
)


def finding(title: str, line: int = 2, confidence: float = 0.8) -> dict:
    return {
        "file": "src/booking.ts",
        "line": line,
        "end_line": None,
        "severity": "high",
        "category": "correctness",
        "title": title,
        "explanation": "because",
        "suggestion": None,
        "confidence": confidence,
    }


def settings(prompt: str = "v3"):
    return load_settings(_env_file=None, provider="fake", model="fake-model", prompt_version=prompt)


def test_prompt_versions_name_review_and_verify_prompts() -> None:
    assert available_prompts() == ["v1", "v2", "v3"]
    assert prompt_config("v3").review == "v2"
    assert prompt_config("v3").verify == "v3-verify"
    assert prompt_config("v2").verify is None
    assert "second reviewer" in load_prompt("v3-verify")


def test_v3_verifies_every_model_finding_and_drops_rejections() -> None:
    fake = FakeProvider(
        [
            {
                "findings": [finding("Off by one"), finding("Imaginary problem", line=5)],
                "summary": "s",
            },
            {
                "verdicts": [
                    {"id": 1, "verdict": "confirmed", "reason": "<= admits count == capacity"},
                    {"id": 2, "verdict": "rejected", "reason": "throwing here is intended"},
                ]
            },
        ]
    )
    run = run_review(DIFF, settings(), fake)
    assert [f.title for f in run.report.model_findings] == ["Off by one"]
    kept = run.report.model_findings[0]
    assert (kept.verdict, kept.verdict_reason) == ("confirmed", "<= admits count == capacity")
    assert run.report.rejected == 1
    assert run.report.requests == 2
    assert any("second opinion rejected" in note for note in run.report.notes)
    verify_request = fake.requests[1]
    assert verify_request.output_schema == VERIFY_SCHEMA
    assert "## Finding 1" in verify_request.user
    assert "## Finding 2" in verify_request.user
    assert "    2 +  if (count <= capacity) {" in verify_request.user
    assert fake.requests[0].system == load_prompt("v2")
    markdown = render_markdown(run.report)
    assert "second opinion: 1 rejected" in markdown
    assert "model · confirmed" in markdown


def test_v2_and_v1_do_not_verify() -> None:
    fake = FakeProvider([{"findings": [finding("Off by one")], "summary": ""}])
    run = run_review(DIFF, settings("v2"), fake)
    assert run.report.requests == 1
    assert run.report.verified is False
    assert run.report.model_findings[0].verdict is None


def test_verifier_failures_keep_findings_unverified() -> None:
    fake = FakeProvider(
        [
            {"findings": [finding("Off by one")], "summary": ""},
            "not json at all",
        ]
    )
    run = run_review(DIFF, settings(), fake)
    assert [f.title for f in run.report.model_findings] == ["Off by one"]
    assert run.report.model_findings[0].verdict is None
    assert any("posted unverified" in note for note in run.report.notes)
    assert run.report.errors
    assert "verify 1/1" in run.report.errors[0]

    limited = FakeProvider(
        [
            {"findings": [finding("Off by one")], "summary": ""},
            LLMError("rate_limit", "daily cap", retryable=True),
        ]
    )
    with pytest.raises(LLMError, match="rate_limit"):
        run_review(DIFF, settings(), limited)


def test_verify_batches_of_ten_and_missing_verdicts() -> None:
    many = [finding(f"Finding {i}", line=2) for i in range(12)]
    fake = FakeProvider(
        [
            {"findings": many, "summary": ""},
            {"verdicts": [{"id": i, "verdict": "plausible", "reason": "r"} for i in range(1, 11)]},
            {"verdicts": [{"id": 11, "verdict": "rejected", "reason": "no"}]},  # 12 missing
        ]
    )
    run = run_review(
        DIFF,
        load_settings(
            _env_file=None,
            provider="fake",
            model="m",
            prompt_version="v3",
            max_findings=20,
            min_confidence=0.0,
        ),
        fake,
    )
    assert run.report.requests == 3
    assert run.report.rejected == 1
    assert len(run.report.model_findings) == 11
    assert sum(1 for f in run.report.model_findings if f.verdict is None) == 1  # unverified
    assert fake.requests[1].user.count("## Finding") == 10
    assert fake.requests[2].user.count("## Finding") == 2

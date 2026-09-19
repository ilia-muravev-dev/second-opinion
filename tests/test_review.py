import json
from pathlib import Path

import pytest

from second_opinion.config import load_settings
from second_opinion.diff import parse_diff
from second_opinion.llm import CassetteProvider, FakeProvider, LLMError, LLMRequest
from second_opinion.pipeline import run_review
from second_opinion.report import render_inline_comment, render_markdown
from second_opinion.review import REVIEW_SCHEMA, load_prompt, review_diff
from second_opinion.review.reviewer import parse_output

from .helpers import make_diff

DIFF = make_diff(
    {
        "src/booking.ts": (
            "export function reserve(count: number, capacity: number) {\n"
            "  if (count < capacity) {\n"
            "    return insert();\n"
            "  }\n"
            "  throw new NoCapacity();\n"
            "}\n",
            "export function reserve(count: number, capacity: number) {\n"
            "  if (count <= capacity) {\n"
            "    return insert();\n"
            "  }\n"
            "  throw new NoCapacity();\n"
            "}\n",
        )
    }
)


def finding(**overrides):
    base = {
        "file": "src/booking.ts",
        "line": 2,
        "end_line": None,
        "severity": "high",
        "category": "correctness",
        "title": "Off-by-one lets one booking too many through",
        "explanation": "`<=` admits count == capacity, so the resource is overbooked by one.",
        "suggestion": "Use `<`.",
        "confidence": 0.9,
    }
    return {**base, **overrides}


def settings(**overrides):
    return load_settings(_env_file=None, provider="fake", model="fake-model", **overrides)


def test_review_turns_model_output_into_anchored_findings() -> None:
    fake = FakeProvider([{"findings": [finding()], "summary": "Loosens the capacity check."}])
    run = run_review(DIFF, settings(), fake)
    [model] = run.report.model_findings
    assert (model.file, model.line, model.severity, model.confidence) == (
        "src/booking.ts",
        2,
        "high",
        0.9,
    )
    assert run.report.summaries == ["Loosens the capacity check."]
    assert run.report.requests == 1
    assert run.report.cost_usd == 0.0
    markdown = render_markdown(run.report)
    assert "<!-- second-opinion -->" in markdown
    assert "`src/booking.ts:2`" in markdown
    assert "Off-by-one lets one booking too many through" in markdown
    assert "fake/fake-model" in markdown
    assert "prompt v1" in markdown
    inline = render_inline_comment(model)
    assert inline.startswith("🔴 **Off-by-one")
    assert "confidence 90%" in inline


def test_the_prompt_and_schema_reach_the_model() -> None:
    fake = FakeProvider()
    run_review(DIFF, settings(), fake, title="Loosen capacity check")
    [request] = fake.requests
    assert request.system == load_prompt("v1")
    assert request.output_schema == REVIEW_SCHEMA
    assert "Pull request: Loosen capacity check" in request.user
    assert "    2 +  if (count <= capacity) {" in request.user
    assert request.model == "fake-model"


def test_unanchorable_findings_are_kept_for_the_summary_only() -> None:
    fake = FakeProvider(
        [
            {
                "findings": [
                    finding(line=400, title="Somewhere far away"),
                    finding(file="src/other.ts", title="Unknown file"),
                ],
                "summary": "",
            }
        ]
    )
    run = run_review(DIFF, settings(), fake)
    assert [f.title for f in run.report.model_findings] == ["Somewhere far away"]
    assert run.report.model_findings[0].line is None
    assert run.model_result is not None
    assert (run.model_result.stats.unanchored, run.model_result.stats.unknown_file) == (1, 1)
    assert "not in the diff" in render_markdown(run.report) or run.report.notes


def test_confidence_floor_dedupe_and_cap() -> None:
    raw = [
        finding(confidence=0.3, title="Too unsure"),
        finding(title="Same thing said twice", confidence=0.6),
        finding(title="same thing said TWICE!", confidence=0.8),
        *[finding(title=f"Finding number {i}", confidence=0.7) for i in range(20)],
    ]
    fake = FakeProvider([{"findings": raw, "summary": ""}])
    run = run_review(DIFF, settings(max_findings=5, min_confidence=0.5), fake)
    model = run.report.model_findings
    assert len(model) == 5
    assert "Too unsure" not in [f.title for f in model]
    stats = run.model_result.stats  # type: ignore[union-attr]
    assert (stats.received, stats.below_confidence, stats.duplicates) == (23, 1, 1)
    assert stats.over_cap == 21 - 5
    kept_duplicate = next(f for f in model if "said" in f.title.lower())
    assert kept_duplicate.confidence == 0.8


def test_malformed_answers_are_reported_not_fatal() -> None:
    fake = FakeProvider(["this is not json"])
    run = run_review(DIFF, settings(), fake)
    assert run.report.model_findings == []
    assert run.report.errors
    assert "did not return JSON" in run.report.errors[0]
    assert "Problems during the review" in render_markdown(run.report)


def test_partially_valid_answers_keep_the_valid_findings() -> None:
    output = parse_output(
        json.dumps({"findings": [finding(), {"file": "x", "severity": "weird"}], "summary": "s"})
    )
    assert len(output.findings) == 1
    assert output.summary == "s"
    bare_list = parse_output(json.dumps([finding()]))
    assert len(bare_list.findings) == 1
    with pytest.raises(ValueError, match="does not match the schema"):
        parse_output(json.dumps({"findings": [{"nonsense": True}]}))


def test_rate_limits_stop_the_review_immediately() -> None:
    fake = FakeProvider([LLMError("rate_limit", "daily limit", retryable=True)])
    with pytest.raises(LLMError, match="rate_limit"):
        run_review(DIFF, settings(), fake)


def test_other_model_errors_are_reported_and_the_review_goes_on() -> None:
    fake = FakeProvider([LLMError("bad_request", "no answer", retryable=False)])
    run = run_review(DIFF, settings(), fake)
    assert run.report.model_findings == []
    assert run.report.errors == ["part 1/1: bad_request: no answer"]
    assert run.report.check_findings == []  # the deterministic layer still reports


def test_big_diffs_are_reviewed_in_parts() -> None:
    corpus = Path(__file__).resolve().parents[1] / "evals" / "corpus" / "slotlock" / "pr-2.diff"
    fake = FakeProvider()
    result = review_diff(
        parse_diff(corpus.read_text()),
        fake,
        model="fake-model",
        prompt_version="v1",
        max_request_tokens=8_000,
        min_confidence=0.5,
        max_findings=10,
        case_id="slotlock-pr2",
    )
    assert result.chunks > 1
    assert result.requests == result.chunks
    assert "Diff part 1 of" in fake.requests[0].user
    assert fake.requests[0].cache_key == {
        "case": "slotlock-pr2",
        "prompt": "v1",
        "chunk": f"1/{result.chunks}",
    }


def test_cassette_records_and_replays(tmp_path: Path) -> None:
    inner = FakeProvider([{"findings": [finding()], "summary": "recorded"}])
    recorder = CassetteProvider(inner, tmp_path, "record")
    request = LLMRequest(
        model="m", system="s", user="u", output_schema=REVIEW_SCHEMA, cache_key={"case": "c1"}
    )
    first = recorder.complete(request)
    assert recorder.misses == 1
    assert list(tmp_path.glob("*.json"))
    replayer = CassetteProvider(FakeProvider(), tmp_path, "replay")
    again = replayer.complete(request)
    assert again.text == first.text
    assert replayer.hits == 1
    with pytest.raises(LLMError, match="cassette_miss"):
        replayer.complete(
            LLMRequest(
                model="m", system="s", user="u", output_schema={}, cache_key={"case": "other"}
            )
        )


def test_percent_confidences_and_loose_labels_are_normalised() -> None:
    output = parse_output(
        json.dumps(
            {
                "findings": [
                    finding(confidence=98, severity="High", category="Error handling"),
                    finding(confidence=0.4, category="bug"),
                ],
                "summary": "",
            }
        )
    )
    assert [f.confidence for f in output.findings] == [0.98, 0.4]
    assert output.findings[0].severity == "high"
    assert output.findings[0].category == "error_handling"
    assert output.findings[1].category == "correctness"


def test_truncated_json_keeps_the_complete_findings() -> None:
    complete = json.dumps({"findings": [finding(title="one"), finding(title="two")]})
    cut = complete[: complete.rfind('"title": "two"') + 10]  # mid second object
    output = parse_output(cut)
    assert [f.title for f in output.findings] == ["one"]
    with pytest.raises(ValueError, match="did not return JSON"):
        parse_output("nothing here")

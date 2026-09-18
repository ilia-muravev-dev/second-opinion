import json

import httpx
import pytest
import respx

from second_opinion.findings import Finding
from second_opinion.github import (
    GitHubClient,
    GitHubError,
    PullRequest,
    event_pull_number,
    post_review,
)
from second_opinion.github.post import inline_comment_for
from second_opinion.llm.provider import LLMUsage
from second_opinion.report import MARKER, ReviewReport

BASE = "https://api.github.test"


def client() -> GitHubClient:
    return GitHubClient("token", base_url=BASE)


def pr() -> PullRequest:
    return PullRequest("o", "r", 7, "Title", "Body", "abc123", "o/r", "main")


def finding(**overrides) -> Finding:
    base = {
        "source": "model",
        "file": "src/a.ts",
        "line": 4,
        "severity": "high",
        "category": "correctness",
        "title": "Off by one",
        "explanation": "because",
        "suggestion": "fix",
        "confidence": 0.9,
    }
    return Finding.model_validate({**base, **overrides})


@respx.mock(base_url=BASE)
def test_reads_pull_request_and_diff(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("/repos/o/r/pulls/7").mock(
        side_effect=lambda request: httpx.Response(
            200,
            text="diff --git a/x b/x\n"
            if request.headers["Accept"] == "application/vnd.github.v3.diff"
            else json.dumps(
                {
                    "title": "T",
                    "body": None,
                    "head": {"sha": "abc", "repo": {"full_name": "o/r"}},
                    "base": {"ref": "main"},
                }
            ),
        )
    )
    pull = client().get_pull("o", "r", 7)
    assert (pull.title, pull.head_sha, pull.head_repo, pull.base_ref) == ("T", "abc", "o/r", "main")
    assert client().get_diff("o", "r", 7).startswith("diff --git")


@respx.mock(base_url=BASE)
def test_errors_carry_github_message(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("/repos/o/r/pulls/7").respond(404, json={"message": "Not Found"})
    with pytest.raises(GitHubError, match="404: Not Found"):
        client().get_pull("o", "r", 7)


@respx.mock(base_url=BASE)
def test_posts_inline_review_and_creates_summary(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("/repos/o/r/pulls/7/comments").respond(200, json=[])
    review = respx_mock.post("/repos/o/r/pulls/7/reviews").respond(200, json={"id": 1})
    respx_mock.get("/repos/o/r/issues/7/comments").respond(200, json=[])
    created = respx_mock.post("/repos/o/r/issues/7/comments").respond(201, json={"id": 2})
    report = ReviewReport(
        findings=[finding(), finding(line=None, title="Unanchored")], usage=LLMUsage()
    )
    outcome = post_review(client(), pr(), report, mode="review")
    assert (outcome.inline_posted, outcome.summary_updated) == (1, True)
    payload = json.loads(review.calls[0].request.content)
    assert payload["commit_id"] == "abc123"
    assert payload["event"] == "COMMENT"
    [comment] = payload["comments"]
    assert (comment["path"], comment["line"], comment["side"]) == ("src/a.ts", 4, "RIGHT")
    assert "<!-- so:fp:" in comment["body"]
    summary = json.loads(created.calls[0].request.content)["body"]
    assert MARKER in summary
    assert "Unanchored" in summary


@respx.mock(base_url=BASE, assert_all_called=False)
def test_rerun_skips_seen_fingerprints_and_edits_the_summary(respx_mock: respx.MockRouter) -> None:
    f = finding()
    respx_mock.get("/repos/o/r/pulls/7/comments").respond(
        200, json=[{"body": f"old text\n<!-- so:fp:{f.fingerprint} -->"}]
    )
    review = respx_mock.post("/repos/o/r/pulls/7/reviews").respond(200, json={"id": 1})
    respx_mock.get("/repos/o/r/issues/7/comments").respond(
        200, json=[{"id": 55, "body": f"{MARKER}\nold summary"}]
    )
    patched = respx_mock.patch("/repos/o/r/issues/comments/55").respond(200, json={"id": 55})
    outcome = post_review(client(), pr(), ReviewReport(findings=[f]), mode="review")
    assert (outcome.inline_posted, outcome.inline_skipped_seen) == (0, 1)
    assert not review.called
    assert patched.called


@respx.mock(base_url=BASE)
def test_refused_anchors_fall_back_to_the_summary(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("/repos/o/r/pulls/7/comments").respond(200, json=[])
    respx_mock.post("/repos/o/r/pulls/7/reviews").respond(
        422, json={"message": "Validation Failed: line must be part of the diff"}
    )
    respx_mock.get("/repos/o/r/issues/7/comments").respond(200, json=[])
    created = respx_mock.post("/repos/o/r/issues/7/comments").respond(201, json={"id": 2})
    outcome = post_review(client(), pr(), ReviewReport(findings=[finding()]), mode="review")
    assert outcome.inline_fell_back
    assert "refused the inline anchors" in json.loads(created.calls[0].request.content)["body"]


@respx.mock(base_url=BASE)
def test_summary_mode_posts_no_inline_comments(respx_mock: respx.MockRouter) -> None:
    respx_mock.get("/repos/o/r/issues/7/comments").respond(200, json=[])
    respx_mock.post("/repos/o/r/issues/7/comments").respond(201, json={"id": 2})
    outcome = post_review(client(), pr(), ReviewReport(findings=[finding()]), mode="summary")
    assert (outcome.inline_posted, outcome.summary_updated) == (0, True)
    assert (
        post_review(client(), pr(), ReviewReport(findings=[]), mode="none").summary_updated is False
    )


def test_ranges_become_start_line_and_line() -> None:
    comment = inline_comment_for(finding(line=4, end_line=6))
    assert comment is not None
    assert (comment.start_line, comment.line) == (4, 6)
    assert comment.payload()["start_side"] == "RIGHT"
    assert inline_comment_for(finding(line=None)) is None


def test_event_pull_number(tmp_path, monkeypatch) -> None:
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"number": 12}}))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    assert event_pull_number() == 12
    monkeypatch.delenv("GITHUB_EVENT_PATH")
    assert event_pull_number() is None

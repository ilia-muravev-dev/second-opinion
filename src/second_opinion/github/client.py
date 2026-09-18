"""The little of GitHub's REST API a reviewer needs: read the pull request and its diff, leave one
review with inline comments, keep one summary comment up to date."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from second_opinion.report import MARKER

FINGERPRINT_TAG = "<!-- so:fp:{fingerprint} -->"


@dataclass(frozen=True)
class PullRequest:
    owner: str
    repo: str
    number: int
    title: str
    body: str | None
    head_sha: str
    head_repo: str
    base_ref: str

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repo}"


@dataclass(frozen=True)
class InlineComment:
    path: str
    line: int
    body: str
    start_line: int | None = None

    def payload(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "path": self.path,
            "line": self.line,
            "side": "RIGHT",
            "body": self.body,
        }
        if self.start_line is not None and self.start_line < self.line:
            data["start_line"] = self.start_line
            data["start_side"] = "RIGHT"
        return data


class GitHubError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"GitHub API {status}: {message}")
        self.status = status


class GitHubClient:
    def __init__(
        self,
        token: str,
        *,
        base_url: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = (
            base_url or os.environ.get("GITHUB_API_URL") or "https://api.github.com"
        ).rstrip("/")
        self.client = client or httpx.Client(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "second-opinion",
            },
            timeout=30.0,
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response = self.client.request(method, path, **kwargs)
        if response.status_code >= 400:
            try:
                message = str(response.json().get("message", response.text))
            except ValueError:
                message = response.text
            raise GitHubError(response.status_code, message)
        return response

    def get_pull(self, owner: str, repo: str, number: int) -> PullRequest:
        data = self._request("GET", f"/repos/{owner}/{repo}/pulls/{number}").json()
        return PullRequest(
            owner=owner,
            repo=repo,
            number=number,
            title=str(data["title"]),
            body=data.get("body"),
            head_sha=str(data["head"]["sha"]),
            head_repo=str((data["head"].get("repo") or {}).get("full_name") or f"{owner}/{repo}"),
            base_ref=str(data["base"]["ref"]),
        )

    def get_diff(self, owner: str, repo: str, number: int) -> str:
        response = self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls/{number}",
            headers={"Accept": "application/vnd.github.v3.diff"},
        )
        return response.text

    def existing_fingerprints(self, owner: str, repo: str, number: int) -> set[str]:
        """Fingerprints of inline comments this tool already left on the pull request."""
        found: set[str] = set()
        page = 1
        while True:
            data = self._request(
                "GET",
                f"/repos/{owner}/{repo}/pulls/{number}/comments",
                params={"per_page": 100, "page": page},
            ).json()
            for comment in data:
                body = str(comment.get("body", ""))
                marker = "<!-- so:fp:"
                start = body.find(marker)
                if start >= 0:
                    end = body.find("-->", start)
                    found.add(body[start + len(marker) : end].strip())
            if len(data) < 100:
                return found
            page += 1

    def create_review(
        self,
        pr: PullRequest,
        *,
        body: str,
        comments: list[InlineComment],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "commit_id": pr.head_sha,
            "event": "COMMENT",
            "body": body,
            "comments": [c.payload() for c in comments],
        }
        response = self._request(
            "POST", f"/repos/{pr.owner}/{pr.repo}/pulls/{pr.number}/reviews", json=payload
        )
        return dict(response.json())

    def upsert_summary(self, pr: PullRequest, body: str) -> dict[str, Any]:
        """One summary comment per pull request, found by its marker and edited in place."""
        page = 1
        while True:
            comments = self._request(
                "GET",
                f"/repos/{pr.owner}/{pr.repo}/issues/{pr.number}/comments",
                params={"per_page": 100, "page": page},
            ).json()
            for comment in comments:
                if MARKER in str(comment.get("body", "")):
                    response = self._request(
                        "PATCH",
                        f"/repos/{pr.owner}/{pr.repo}/issues/comments/{comment['id']}",
                        json={"body": body},
                    )
                    return dict(response.json())
            if len(comments) < 100:
                break
            page += 1
        response = self._request(
            "POST", f"/repos/{pr.owner}/{pr.repo}/issues/{pr.number}/comments", json={"body": body}
        )
        return dict(response.json())


def event_pull_number() -> int | None:
    """The pull request number from the Actions event payload, when running in Actions."""
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path or not Path(path).exists():
        return None
    try:
        event = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    number = (event.get("pull_request") or {}).get("number") or (event.get("issue") or {}).get(
        "number"
    )
    return int(number) if number else None


def repo_from_env() -> tuple[str, str] | None:
    slug = os.environ.get("GITHUB_REPOSITORY")
    if slug and "/" in slug:
        owner, repo = slug.split("/", 1)
        return owner, repo
    return None

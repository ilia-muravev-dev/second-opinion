"""A parser for git's unified diff output (`git diff`, `gh pr diff`, the GitHub API's .diff).
Small on purpose: headers, renames, binaries, hunks with both line numbers, no-newline markers."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from second_opinion.diff.model import Diff, DiffLine, FileDiff, FileStatus, Hunk

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")
_DIFF_GIT = re.compile(r'^diff --git (?:"?a/(.+?)"?) (?:"?b/(.+?)"?)$')

LANGUAGES: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mts": "typescript",
    ".js": "javascript",
    ".mjs": "javascript",
    ".jsx": "javascript",
    ".sql": "sql",
    ".prisma": "prisma",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".json": "json",
    ".md": "markdown",
    ".toml": "toml",
    ".sh": "shell",
    ".html": "html",
    ".css": "css",
}


def language_of(path: str) -> str | None:
    name = PurePosixPath(path).name
    if name in {"justfile", "Justfile"}:
        return "just"
    if name in {"Dockerfile"} or name.startswith("Dockerfile."):
        return "dockerfile"
    return LANGUAGES.get(PurePosixPath(path).suffix.lower())


class _FileBuilder:
    def __init__(self, old_path: str, new_path: str) -> None:
        self.old_path = old_path
        self.new_path = new_path
        self.status: FileStatus = "modified"
        self.is_binary = False
        self.hunks: list[Hunk] = []
        self.renamed = False

    def build(self) -> FileDiff:
        path = self.new_path if self.status != "deleted" else self.old_path
        old_path = self.old_path if self.renamed or self.status == "deleted" else None
        if self.status == "deleted":
            old_path = self.old_path
        return FileDiff(
            path=path,
            status=self.status,
            old_path=old_path,
            is_binary=self.is_binary,
            hunks=tuple(self.hunks),
            language=language_of(path),
        )


def parse_diff(text: str) -> Diff:
    files: list[FileDiff] = []
    current: _FileBuilder | None = None
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        header = _DIFF_GIT.match(line)
        if header:
            if current is not None:
                files.append(current.build())
            current = _FileBuilder(header.group(1), header.group(2))
            i += 1
            continue
        if current is None:
            i += 1
            continue
        if line.startswith("new file mode"):
            current.status = "added"
        elif line.startswith("deleted file mode"):
            current.status = "deleted"
        elif line.startswith("rename from "):
            current.renamed = True
            current.status = "renamed"
            current.old_path = line[len("rename from ") :]
        elif line.startswith("rename to "):
            current.new_path = line[len("rename to ") :]
        elif line.startswith("Binary files ") or line.startswith("GIT binary patch"):
            current.is_binary = True
        elif line.startswith("@@"):
            hunk, i = _parse_hunk(lines, i)
            current.hunks.append(hunk)
            continue
        i += 1
    if current is not None:
        files.append(current.build())
    return Diff(files=tuple(files))


def _parse_hunk(lines: list[str], start: int) -> tuple[Hunk, int]:
    match = _HUNK.match(lines[start])
    if not match:
        msg = f"malformed hunk header: {lines[start]!r}"
        raise ValueError(msg)
    old_start = int(match.group(1))
    old_len = int(match.group(2)) if match.group(2) is not None else 1
    new_start = int(match.group(3))
    new_len = int(match.group(4)) if match.group(4) is not None else 1
    section = match.group(5).strip()
    body: list[DiffLine] = []
    old_no, new_no = old_start, new_start
    old_seen = new_seen = 0
    i = start + 1
    while i < len(lines) and (old_seen < old_len or new_seen < new_len):
        raw = lines[i]
        if raw.startswith("\\"):  # "\ No newline at end of file"
            i += 1
            continue
        if raw.startswith("+"):
            body.append(DiffLine("added", raw[1:], None, new_no))
            new_no += 1
            new_seen += 1
        elif raw.startswith("-"):
            body.append(DiffLine("removed", raw[1:], old_no, None))
            old_no += 1
            old_seen += 1
        elif raw.startswith(" ") or raw == "":
            body.append(DiffLine("context", raw[1:] if raw else "", old_no, new_no))
            old_no += 1
            new_no += 1
            old_seen += 1
            new_seen += 1
        else:
            break  # the next file header or garbage: the hunk ends here
        i += 1
    # a trailing "\ No newline at end of file" belongs to this hunk
    while i < len(lines) and lines[i].startswith("\\"):
        i += 1
    return Hunk(old_start, old_len, new_start, new_len, section, tuple(body)), i

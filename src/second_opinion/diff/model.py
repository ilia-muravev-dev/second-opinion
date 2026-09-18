"""The shape of a pull request's diff. Line numbers are kept for both sides because a review
comment is anchored to a line on the new side, and only lines inside a hunk can carry one."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

FileStatus = Literal["added", "modified", "deleted", "renamed"]
LineKind = Literal["context", "added", "removed"]


@dataclass(frozen=True)
class DiffLine:
    kind: LineKind
    content: str
    old_no: int | None
    new_no: int | None

    @property
    def marker(self) -> str:
        return {"context": " ", "added": "+", "removed": "-"}[self.kind]


@dataclass(frozen=True)
class Hunk:
    old_start: int
    old_len: int
    new_start: int
    new_len: int
    section: str
    lines: tuple[DiffLine, ...]

    @property
    def new_end(self) -> int:
        """The last new-side line number covered by this hunk (inclusive)."""
        return self.new_start + max(self.new_len, 1) - 1

    def header(self) -> str:
        tail = f" {self.section}" if self.section else ""
        return f"@@ -{self.old_start},{self.old_len} +{self.new_start},{self.new_len} @@{tail}"


@dataclass(frozen=True)
class FileDiff:
    path: str
    status: FileStatus
    old_path: str | None = None
    is_binary: bool = False
    hunks: tuple[Hunk, ...] = ()
    language: str | None = None

    @property
    def added(self) -> list[DiffLine]:
        return [line for hunk in self.hunks for line in hunk.lines if line.kind == "added"]

    @property
    def removed(self) -> list[DiffLine]:
        return [line for hunk in self.hunks for line in hunk.lines if line.kind == "removed"]

    @property
    def changed_lines(self) -> int:
        return sum(1 for hunk in self.hunks for line in hunk.lines if line.kind != "context")

    def covers_new_line(self, line: int) -> bool:
        """Whether a review comment can be anchored to new-side `line` (it sits in a hunk)."""
        return any(
            candidate.new_no == line
            for hunk in self.hunks
            for candidate in hunk.lines
            if candidate.kind != "removed"
        )

    def line_at(self, line: int) -> DiffLine | None:
        for hunk in self.hunks:
            for candidate in hunk.lines:
                if candidate.new_no == line and candidate.kind != "removed":
                    return candidate
        return None


@dataclass(frozen=True)
class Diff:
    files: tuple[FileDiff, ...] = field(default_factory=tuple)

    def file(self, path: str) -> FileDiff | None:
        return next((f for f in self.files if f.path == path), None)

    @property
    def changed_lines(self) -> int:
        return sum(f.changed_lines for f in self.files)

"""What a reviewer would not read: lockfiles, generated code, binaries, recorded fixtures, vendored
trees, and files so large that a review of them is a job of its own. Skipped files are reported,
never silently dropped."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass

from second_opinion.diff.model import Diff, FileDiff

# (glob, reason) — matched against the full path; order matters only for the reason given.
SKIP_PATTERNS: tuple[tuple[str, str], ...] = (
    ("**/pnpm-lock.yaml", "lockfile"),
    ("pnpm-lock.yaml", "lockfile"),
    ("**/package-lock.json", "lockfile"),
    ("package-lock.json", "lockfile"),
    ("**/yarn.lock", "lockfile"),
    ("yarn.lock", "lockfile"),
    ("**/uv.lock", "lockfile"),
    ("uv.lock", "lockfile"),
    ("**/poetry.lock", "lockfile"),
    ("poetry.lock", "lockfile"),
    ("**/Cargo.lock", "lockfile"),
    ("**/go.sum", "lockfile"),
    ("**/generated/**", "generated"),
    ("**/__generated__/**", "generated"),
    ("**/*.generated.*", "generated"),
    ("**/schema.d.ts", "generated"),
    ("**/*.min.js", "minified"),
    ("**/*.min.css", "minified"),
    ("**/*.map", "source map"),
    ("**/*.snap", "snapshot"),
    ("**/cassettes/**", "recorded fixture"),
    ("**/__snapshots__/**", "snapshot"),
    ("**/node_modules/**", "vendored"),
    ("**/vendor/**", "vendored"),
    ("**/dist/**", "build output"),
    ("**/build/**", "build output"),
    ("**/*.svg", "image"),
    ("**/*.png", "image"),
    ("**/*.jpg", "image"),
    ("**/*.jpeg", "image"),
    ("**/*.gif", "image"),
    ("**/*.ico", "image"),
    ("**/*.webp", "image"),
    ("**/*.pdf", "binary document"),
    ("**/*.woff", "font"),
    ("**/*.woff2", "font"),
    ("**/*.ttf", "font"),
)

MAX_CHANGED_LINES_PER_FILE = 1500


@dataclass(frozen=True)
class SkippedFile:
    path: str
    reason: str


@dataclass(frozen=True)
class FilteredDiff:
    diff: Diff
    skipped: tuple[SkippedFile, ...]

    @property
    def files(self) -> tuple[FileDiff, ...]:
        return self.diff.files


def skip_reason(file: FileDiff) -> str | None:
    if file.is_binary:
        return "binary"
    for pattern, reason in SKIP_PATTERNS:
        if fnmatch.fnmatch(file.path, pattern):
            return reason
    if file.status == "deleted":
        return "deleted"
    if file.changed_lines > MAX_CHANGED_LINES_PER_FILE:
        return f"too large ({file.changed_lines} changed lines)"
    return None


def filter_diff(diff: Diff) -> FilteredDiff:
    kept: list[FileDiff] = []
    skipped: list[SkippedFile] = []
    for file in diff.files:
        reason = skip_reason(file)
        if reason is None:
            kept.append(file)
        else:
            skipped.append(SkippedFile(file.path, reason))
    return FilteredDiff(Diff(tuple(kept)), tuple(skipped))

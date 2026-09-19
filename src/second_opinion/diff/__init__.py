"""Unified diffs as data: parsed, filtered, budgeted and rendered for a model."""

from second_opinion.diff.chunk import Chunk, chunk_diff, render_chunk, render_file
from second_opinion.diff.filters import FilteredDiff, SkippedFile, filter_diff
from second_opinion.diff.model import Diff, DiffLine, FileDiff, FileStatus, Hunk
from second_opinion.diff.parse import parse_diff
from second_opinion.diff.serialize import rebuild_file, serialize_diff
from second_opinion.diff.tokens import estimate_tokens

__all__ = [
    "Chunk",
    "Diff",
    "DiffLine",
    "FileDiff",
    "FileStatus",
    "FilteredDiff",
    "Hunk",
    "SkippedFile",
    "chunk_diff",
    "estimate_tokens",
    "filter_diff",
    "parse_diff",
    "rebuild_file",
    "render_chunk",
    "render_file",
    "serialize_diff",
]

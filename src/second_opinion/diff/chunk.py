"""Rendering a diff for a model, within a token budget. Every changed line is shown with its
new-side line number so a finding can cite exactly the line a comment will be anchored to.
Files are grouped greedily into chunks; a single file larger than the budget is cut at a hunk
boundary and the cut is announced in the rendering."""

from __future__ import annotations

from dataclasses import dataclass

from second_opinion.diff.model import Diff, DiffLine, FileDiff, Hunk
from second_opinion.diff.tokens import estimate_tokens


@dataclass(frozen=True)
class Chunk:
    index: int
    total: int
    files: tuple[FileDiff, ...]
    text: str
    tokens: int
    truncated_files: tuple[str, ...] = ()


def render_line(line: DiffLine) -> str:
    number = f"{line.new_no:>5}" if line.new_no is not None else "     "
    return f"{number} {line.marker}{line.content}"


def render_hunk(hunk: Hunk) -> str:
    return "\n".join([hunk.header(), *(render_line(line) for line in hunk.lines)])


def render_file(file: FileDiff, hunks: tuple[Hunk, ...] | None = None) -> str:
    status = file.status if file.old_path is None else f"{file.status} from {file.old_path}"
    header = f"### {file.path} ({status})"
    body = "\n\n".join(render_hunk(h) for h in (hunks if hunks is not None else file.hunks))
    return f"{header}\n{body}" if body else header


def chunk_diff(diff: Diff, max_tokens: int) -> list[Chunk]:
    """Greedy grouping in file order; the numbers in `index`/`total` are 1-based."""
    groups: list[tuple[list[FileDiff], list[str], list[str]]] = []
    current_files: list[FileDiff] = []
    current_texts: list[str] = []
    current_truncated: list[str] = []
    current_tokens = 0

    def flush() -> None:
        nonlocal current_files, current_texts, current_truncated, current_tokens
        if current_files:
            groups.append((current_files, current_texts, current_truncated))
        current_files, current_texts, current_truncated, current_tokens = [], [], [], 0

    for file in diff.files:
        text = render_file(file)
        tokens = estimate_tokens(text)
        if tokens > max_tokens:
            flush()
            text, cut = _truncate_file(file, max_tokens)
            groups.append(([file], [text], [file.path] if cut else []))
            continue
        if current_tokens + tokens > max_tokens and current_files:
            flush()
        current_files.append(file)
        current_texts.append(text)
        current_tokens += tokens
    flush()

    total = len(groups)
    return [
        Chunk(
            index=i + 1,
            total=total,
            files=tuple(files),
            text="\n\n".join(texts),
            tokens=estimate_tokens("\n\n".join(texts)),
            truncated_files=tuple(truncated),
        )
        for i, (files, texts, truncated) in enumerate(groups)
    ]


def _truncate_file(file: FileDiff, max_tokens: int) -> tuple[str, bool]:
    kept: list[Hunk] = []
    used = estimate_tokens(render_file(file, ()))
    for hunk in file.hunks:
        cost = estimate_tokens(render_hunk(hunk)) + 2
        if used + cost > max_tokens:
            break
        kept.append(hunk)
        used += cost
    cut = len(kept) < len(file.hunks)
    text = render_file(file, tuple(kept))
    if cut:
        omitted = len(file.hunks) - len(kept)
        text += f"\n\n[… {omitted} more hunk(s) of {file.path} not shown: over the review budget]"
    return text, cut


def render_chunk(chunk: Chunk) -> str:
    return chunk.text

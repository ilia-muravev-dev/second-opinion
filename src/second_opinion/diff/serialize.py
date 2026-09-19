"""The inverse of the parser: a Diff back to unified diff text, with hunk headers recomputed from
the lines, so a mutated diff is as well-formed as the original."""

from __future__ import annotations

from second_opinion.diff.model import Diff, DiffLine, FileDiff, Hunk


def renumber(lines: list[DiffLine], old_start: int, new_start: int) -> tuple[DiffLine, ...]:
    """Assign old/new line numbers to a hunk's lines from its start positions."""
    out: list[DiffLine] = []
    old_no, new_no = old_start, new_start
    for line in lines:
        if line.kind == "added":
            out.append(DiffLine("added", line.content, None, new_no))
            new_no += 1
        elif line.kind == "removed":
            out.append(DiffLine("removed", line.content, old_no, None))
            old_no += 1
        else:
            out.append(DiffLine("context", line.content, old_no, new_no))
            old_no += 1
            new_no += 1
    return tuple(out)


def rebuild_hunk(hunk: Hunk, lines: list[DiffLine], new_start: int) -> Hunk:
    numbered = renumber(lines, hunk.old_start, new_start)
    old_len = sum(1 for line in numbered if line.kind != "added")
    new_len = sum(1 for line in numbered if line.kind != "removed")
    return Hunk(hunk.old_start, old_len, new_start, new_len, hunk.section, numbered)


def rebuild_file(file: FileDiff, hunks: list[Hunk]) -> FileDiff:
    """Re-derive new-side starts after edits changed the hunks' lengths; old starts are kept."""
    rebuilt: list[Hunk] = []
    shift = 0
    for hunk in hunks:
        new_start = hunk.new_start + shift
        fixed = rebuild_hunk(hunk, list(hunk.lines), new_start)
        shift += fixed.new_len - hunk.new_len
        rebuilt.append(fixed)
    return FileDiff(
        path=file.path,
        status=file.status,
        old_path=file.old_path,
        is_binary=file.is_binary,
        hunks=tuple(rebuilt),
        language=file.language,
    )


def serialize_file(file: FileDiff) -> str:
    old = file.old_path or file.path
    new = file.path
    lines = [f"diff --git a/{old} b/{new}"]
    if file.status == "added":
        lines.append("new file mode 100644")
    elif file.status == "deleted":
        lines.append("deleted file mode 100644")
    elif file.status == "renamed":
        lines.append(f"rename from {old}")
        lines.append(f"rename to {new}")
    if file.is_binary:
        lines.append(
            f"Binary files {'/dev/null' if file.status == 'added' else 'a/' + old} and "
            f"{'/dev/null' if file.status == 'deleted' else 'b/' + new} differ"
        )
        return "\n".join(lines) + "\n"
    if file.hunks:
        lines.append("--- /dev/null" if file.status == "added" else f"--- a/{old}")
        lines.append("+++ /dev/null" if file.status == "deleted" else f"+++ b/{new}")
    for hunk in file.hunks:
        lines.append(hunk.header())
        for line in hunk.lines:
            lines.append(f"{line.marker}{line.content}")
    return "\n".join(lines) + "\n"


def serialize_diff(diff: Diff) -> str:
    return "".join(serialize_file(file) for file in diff.files)

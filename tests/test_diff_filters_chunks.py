from pathlib import Path

from second_opinion.diff import chunk_diff, estimate_tokens, filter_diff, parse_diff, render_file
from second_opinion.diff.filters import MAX_CHANGED_LINES_PER_FILE, skip_reason
from second_opinion.diff.model import Diff, DiffLine, FileDiff, Hunk

CORPUS = Path(__file__).resolve().parents[1] / "evals" / "corpus"


def test_filters_drop_what_a_reviewer_would_not_read() -> None:
    reasons: dict[str, str] = {}
    kept: set[str] = set()
    for name in ("pr-1.diff", "pr-2.diff"):
        filtered = filter_diff(parse_diff((CORPUS / "slotlock" / name).read_text()))
        reasons.update({s.path: s.reason for s in filtered.skipped})
        kept.update(f.path for f in filtered.files)
    assert reasons["pnpm-lock.yaml"] == "lockfile"
    assert reasons["src/generated/prisma/client.ts"] == "generated"
    assert "prisma/schema.prisma" in kept
    assert "src/app.module.ts" in kept
    assert not any(p.startswith("src/generated/") for p in kept)
    cassettes = filter_diff(parse_diff((CORPUS / "fieldwise" / "pr-5.diff").read_text()))
    assert any(s.reason == "recorded fixture" for s in cassettes.skipped)


def test_binary_deleted_and_huge_files_are_skipped_with_a_reason() -> None:
    binary = FileDiff(path="a.bin", status="modified", is_binary=True)
    deleted = FileDiff(path="gone.py", status="deleted")
    lines = tuple(
        DiffLine("added", f"x = {i}", None, i + 1) for i in range(MAX_CHANGED_LINES_PER_FILE + 1)
    )
    huge = FileDiff(
        path="big.py",
        status="added",
        hunks=(Hunk(0, 0, 1, len(lines), "", lines),),
    )
    assert skip_reason(binary) == "binary"
    assert skip_reason(deleted) == "deleted"
    assert (skip_reason(huge) or "").startswith("too large")
    assert skip_reason(FileDiff(path="src/ok.py", status="modified")) is None


def test_rendering_shows_new_side_line_numbers() -> None:
    diff = parse_diff((Path(__file__).parent / "fixtures" / "small.diff").read_text())
    text = render_file(diff.files[0])
    assert text.startswith("### src/app.ts (modified)\n@@ -1,6 +1,7 @@\n")
    assert "    4 +  const sum = a + b;" in text
    assert "      -  return a + b;" in text
    assert "    1  import { x } from './x';" in text


def test_chunking_respects_the_budget_and_numbers_chunks() -> None:
    diff = filter_diff(parse_diff((CORPUS / "slotlock" / "pr-2.diff").read_text())).diff
    budget = 6_000
    chunks = chunk_diff(diff, budget)
    assert len(chunks) > 1
    assert [c.index for c in chunks] == list(range(1, len(chunks) + 1))
    assert all(c.total == len(chunks) for c in chunks)
    assert all(c.tokens <= budget or c.truncated_files for c in chunks)
    assert [f.path for c in chunks for f in c.files] == [f.path for f in diff.files]
    whole = chunk_diff(diff, 10**6)
    assert len(whole) == 1
    assert whole[0].tokens == estimate_tokens(whole[0].text)


def test_a_file_over_the_budget_is_cut_at_a_hunk_boundary() -> None:
    lines = tuple(DiffLine("added", "x" * 200, None, i + 1) for i in range(200))
    hunks = tuple(Hunk(0, 0, 1 + i * 20, 20, "", lines[i * 20 : (i + 1) * 20]) for i in range(10))
    file = FileDiff(path="big.py", status="added", hunks=hunks)
    chunks = chunk_diff(Diff((file,)), 3_000)
    assert len(chunks) == 1
    assert chunks[0].truncated_files == ("big.py",)
    assert "not shown: over the review budget" in chunks[0].text
    assert chunks[0].tokens <= 3_100

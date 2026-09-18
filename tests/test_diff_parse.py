from pathlib import Path

import pytest

from second_opinion.diff import parse_diff

FIXTURES = Path(__file__).parent / "fixtures"
CORPUS = Path(__file__).resolve().parents[1] / "evals" / "corpus"


def test_parses_statuses_and_line_numbers() -> None:
    diff = parse_diff((FIXTURES / "small.diff").read_text())
    by_path = {f.path: f for f in diff.files}
    assert set(by_path) == {"src/app.ts", "docs/README.md", "logo.png", "old.txt", "new.py"}

    app = by_path["src/app.ts"]
    assert app.status == "modified"
    assert app.language == "typescript"
    assert [line.new_no for line in app.added] == [3, 4, 5, 23]
    assert [line.old_no for line in app.removed] == [3, 4]
    assert app.hunks[0].lines[0].content == "import { x } from './x';"
    assert app.hunks[1].section == "export function unrelated() {"
    assert app.covers_new_line(23)
    assert app.covers_new_line(21)  # context lines are anchorable too
    assert not app.covers_new_line(15)  # between hunks
    assert app.line_at(4) is not None
    assert app.line_at(4).content == "  const sum = a + b;"

    renamed = by_path["docs/README.md"]
    assert renamed.status == "renamed"
    assert renamed.old_path == "README.md"
    assert [line.new_no for line in renamed.added] == [2]

    assert by_path["logo.png"].is_binary
    assert by_path["logo.png"].status == "added"
    assert by_path["old.txt"].status == "deleted"
    assert by_path["old.txt"].hunks[0].new_len == 0
    assert by_path["new.py"].status == "added"
    assert [line.new_no for line in by_path["new.py"].added] == [1, 2, 3]


def test_hunk_header_round_trips() -> None:
    diff = parse_diff((FIXTURES / "small.diff").read_text())
    hunk = diff.files[0].hunks[0]
    assert hunk.header() == "@@ -1,6 +1,7 @@"
    assert hunk.new_end == 7


def test_malformed_hunk_is_an_error() -> None:
    with pytest.raises(ValueError, match="malformed hunk"):
        parse_diff("diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ nonsense @@\n")


@pytest.mark.parametrize(
    "path", sorted(CORPUS.glob("*/*.diff")), ids=lambda p: f"{p.parent.name}/{p.stem}"
)
def test_corpus_parses_consistently(path: Path) -> None:
    """Every hunk's declared lengths match the lines it carries, for every real PR in the corpus."""
    diff = parse_diff(path.read_text())
    assert diff.files, path
    for file in diff.files:
        for hunk in file.hunks:
            old = sum(1 for line in hunk.lines if line.kind != "added")
            new = sum(1 for line in hunk.lines if line.kind != "removed")
            assert (old, new) == (hunk.old_len, hunk.new_len), (file.path, hunk.header())
            new_numbers = [line.new_no for line in hunk.lines if line.new_no is not None]
            assert new_numbers == list(range(hunk.new_start, hunk.new_start + len(new_numbers)))

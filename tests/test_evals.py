import json
from pathlib import Path

from second_opinion.config import load_settings
from second_opinion.diff import parse_diff, serialize_diff
from second_opinion.evals import (
    apply,
    build_cases,
    candidates,
    compute,
    load_operators,
    load_run,
    run_cases,
    run_path,
    score_case,
    slugify,
)
from second_opinion.evals.dataset import write_cases
from second_opinion.evals.mutate import Label
from second_opinion.evals.report import render_comparison, write_report
from second_opinion.findings import Finding
from second_opinion.llm import FakeProvider, LLMError

from .helpers import make_diff

CORPUS = Path(__file__).resolve().parents[1] / "evals" / "corpus"
OPERATORS = load_operators()


def test_serializer_round_trips_the_corpus() -> None:
    for path in sorted(CORPUS.glob("*/*.diff")):
        diff = parse_diff(path.read_text())
        assert parse_diff(serialize_diff(diff)) == diff, path


def test_operators_mutate_one_added_line_and_renumber() -> None:
    diff = parse_diff(
        make_diff(
            {
                "src/x.ts": (
                    "export function f(a: number) {\n  if (a < 3) {\n    return a;\n  }\n"
                    "  throw new Error('x');\n}\n",
                    "export function f(a: number) {\n  if (a < 3) {\n    await g();\n"
                    "    return a;\n  }\n  throw new Error('x');\n}\n",
                )
            }
        )
    )
    found = {c.operator.id for c in candidates(diff, OPERATORS)}
    assert "dropped_await" in found
    assert "off_by_one_lt" not in found  # `a < 3` is a context line, not an added one
    await_candidate = next(
        c for c in candidates(diff, OPERATORS) if c.operator.id == "dropped_await"
    )
    mutated, label = apply(diff, await_candidate)
    assert label.file == "src/x.ts"
    assert label.original == "    await g();"
    assert label.mutated == "    g();"
    line = mutated.file("src/x.ts").line_at(label.line)
    assert line is not None
    assert line.content == "    g();"
    assert parse_diff(serialize_diff(mutated)) == mutated


def test_deleting_a_line_shifts_the_following_lines() -> None:
    source = "function f() {\n  if (bad) {\n    throw new Error('bad');\n  }\n  return 1;\n}\n"
    diff = parse_diff(make_diff({"src/y.ts": source}))
    candidate = next(c for c in candidates(diff, OPERATORS) if c.operator.id == "dropped_throw")
    mutated, label = apply(diff, candidate)
    file = mutated.file("src/y.ts")
    assert file is not None
    assert [line.content for line in file.added] == [
        "function f() {",
        "  if (bad) {",
        "  }",
        "  return 1;",
        "}",
    ]
    assert [line.new_no for line in file.added] == [1, 2, 3, 4, 5]
    assert file.hunks[0].new_len == 5
    assert label.line == 2  # the line before the gap
    assert label.mutated is None


def test_insert_operator_adds_a_secret_after_a_declaration() -> None:
    diff = parse_diff(make_diff({"src/z.py": "import os\n\nTIMEOUT = 5\n"}))
    candidate = next(c for c in candidates(diff, OPERATORS) if c.operator.id == "hardcoded_secret")
    mutated, label = apply(diff, candidate)
    contents = [line.content for line in mutated.file("src/z.py").added]
    assert 'PAYMENT_API_SECRET = "live-' in contents[3]
    assert label.line == 4
    assert label.category == "security"


def test_build_is_deterministic_balanced_and_labelled(tmp_path: Path) -> None:
    first = build_cases()
    second = build_cases()
    assert [c.digest() for c in first.cases] == [c.digest() for c in second.cases]
    mutated = [c for c in first.cases if c.kind == "mutated"]
    clean = [c for c in first.cases if c.kind == "clean"]
    assert len(clean) == 33
    assert len(mutated) >= 50
    operators = {c.labels[0].operator for c in mutated}
    assert len(operators) >= 18
    for case in mutated:
        [label] = case.labels
        file = parse_diff(case.diff).file(label.file)
        assert file is not None
        assert file.covers_new_line(label.line), case.id
    write_cases(first, cases_dir=tmp_path / "cases", index_path=tmp_path / "index.json")
    index = json.loads((tmp_path / "index.json").read_text())
    assert len(index["cases"]) == len(first.cases)


def finding(
    file: str, line: int | None, source: str = "model", category: str = "correctness"
) -> Finding:
    return Finding.model_validate(
        {
            "source": source,
            "check": "secrets" if source == "check" else None,
            "file": file,
            "line": line,
            "severity": "high",
            "category": category,
            "title": f"something at {line}",
            "explanation": "x",
            "confidence": 0.8,
        }
    )


def label(file: str = "src/a.py", line: int = 10, category: str = "correctness") -> Label:
    return Label(file, line, category, "high", "op", "desc", "orig", "mut")


def test_scoring_matches_within_tolerance_once_per_label() -> None:
    score = score_case(
        "c",
        "mutated",
        [label(), label(line=50, category="security")],
        [
            finding("src/a.py", 12),  # within 3 of line 10: hit
            finding("src/a.py", 9),  # a second finding near the same label: unlabelled
            finding("src/a.py", 50, source="check", category="security"),  # a check found it
            finding("src/b.py", 50),  # wrong file
            finding("src/a.py", None),  # unanchored
        ],
    )
    assert (score.labels, score.found) == (2, 2)
    assert (score.model_findings, score.model_hits, score.unlabelled_model) == (4, 1, 3)
    assert (score.check_findings, score.check_hits) == (1, 1)
    assert score.category_agreed == 2


def test_runner_resumes_stops_on_rate_limits_and_reports(tmp_path: Path) -> None:
    cases = build_cases(per_pr=1).cases[:6]
    settings = load_settings(
        _env_file=None, provider="fake", model="fake/model:free", prompt_version="v1"
    )
    oracle = FakeProvider(
        default=lambda request: {
            "findings": [
                {
                    "file": case.labels[0].file,
                    "line": case.labels[0].line,
                    "end_line": None,
                    "severity": "high",
                    "category": case.labels[0].category,
                    "title": "planted",
                    "explanation": "found it",
                    "suggestion": None,
                    "confidence": 0.9,
                }
                for case in cases
                if case.labels and request.cache_key.get("case") == case.id
            ],
            "summary": "",
        }
    )
    runs = tmp_path / "runs"
    outcome = run_cases(cases[:3], settings, oracle, runs_dir=runs)
    assert (outcome.done, outcome.skipped, outcome.stopped_by) == (3, 0, None)
    assert outcome.slug == slugify("fake/model:free", "v1") == "fake-model-free--v1"

    limited = FakeProvider(
        [LLMError("rate_limit", "free-models-per-day", retryable=True)], default=oracle.default
    )
    outcome = run_cases(cases, settings, limited, runs_dir=runs)
    assert (outcome.done, outcome.skipped) == (0, 3)
    assert outcome.stopped_by is not None
    assert "rate_limit" in outcome.stopped_by

    outcome = run_cases(cases, settings, oracle, runs_dir=runs, workers=3)
    assert (outcome.done, outcome.skipped) == (3, 3)
    rows = load_run(run_path(outcome.slug, runs))
    assert len(rows) == 6
    again = run_cases(cases, settings, oracle, runs_dir=runs, resume=False)
    assert again.done == 6
    assert len(run_path(outcome.slug, runs).read_text().splitlines()) == 6  # compacted
    metrics = compute(rows)
    mutated = sum(1 for c in cases if c.kind == "mutated")
    assert (metrics.mutated_cases, metrics.clean_cases) == (mutated, 6 - mutated)
    assert metrics.recall == 1.0
    assert metrics.precision == 1.0
    assert metrics.false_positives_per_clean == 0.0
    assert metrics.cost_usd == 0.0


def test_report_and_comparison_render(tmp_path: Path, monkeypatch) -> None:
    cases = build_cases(per_pr=1).cases[:4]
    settings = load_settings(
        _env_file=None, provider="fake", model="fake-model", prompt_version="v1"
    )
    runs = tmp_path / "runs"
    run_cases(cases, settings, FakeProvider(), runs_dir=runs)
    monkeypatch.setattr("second_opinion.evals.report.run_path", lambda slug: run_path(slug, runs))
    path, metrics = write_report("fake-model--v1", docs_dir=tmp_path / "docs")
    text = path.read_text()
    assert text.startswith("# Eval run `fake-model--v1`")
    assert "| Recall (planted defects found) |" in text
    assert "## Missed" in text
    assert metrics.found == 0
    table = render_comparison(["fake-model--v1", "missing--v9"])
    assert "| `fake-model--v1` | 4 |" in table
    assert "| `missing--v9` | no run |" in table

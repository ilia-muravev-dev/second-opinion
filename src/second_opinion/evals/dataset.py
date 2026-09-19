"""The eval set: every corpus pull request as a clean case, plus up to N mutated copies of it,
each with exactly one planted defect. Generated deterministically from the corpus, the operator
catalogue and a seed; the committed index pins what a run measured."""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from second_opinion.diff import (
    estimate_tokens,
    filter_diff,
    parse_diff,
    render_file,
    serialize_diff,
)
from second_opinion.evals.mutate import (
    Candidate,
    Label,
    Operator,
    apply,
    candidates,
    load_operators,
)

ROOT = Path(__file__).resolve().parents[3]
CORPUS_DIR = ROOT / "evals" / "corpus"
CASES_DIR = ROOT / "evals" / "cases"
INDEX_PATH = ROOT / "evals" / "cases.index.json"
DEFAULT_SEED = 20260918


@dataclass(frozen=True)
class Case:
    id: str
    repo: str
    pr: int
    kind: str  # clean | mutated
    diff: str
    labels: tuple[Label, ...] = ()
    tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "repo": self.repo,
            "pr": self.pr,
            "kind": self.kind,
            "tokens": self.tokens,
            "labels": [label.to_dict() for label in self.labels],
            "diff": self.diff,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Case:
        return cls(
            id=str(data["id"]),
            repo=str(data["repo"]),
            pr=int(data["pr"]),
            kind=str(data["kind"]),
            diff=str(data["diff"]),
            labels=tuple(Label(**label) for label in data.get("labels", [])),
            tokens=int(data.get("tokens", 0)),
        )

    def digest(self) -> str:
        return hashlib.sha256(self.diff.encode()).hexdigest()[:16]


@dataclass
class BuildReport:
    cases: list[Case] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)


def corpus_diffs(corpus_dir: Path = CORPUS_DIR) -> list[tuple[str, int, Path]]:
    found: list[tuple[str, int, Path]] = []
    for path in sorted(corpus_dir.glob("*/pr-*.diff")):
        found.append((path.parent.name, int(path.stem.split("-", 1)[1]), path))
    return sorted(found)


def pick_candidates(
    options: list[Candidate],
    rng: random.Random,
    usage: dict[str, int],
    per_pr: int,
) -> list[Candidate]:
    """Up to `per_pr` candidates with distinct operators and files, preferring operators the set
    has seen least so far — so the catalogue is covered evenly instead of by frequency."""
    chosen: list[Candidate] = []
    by_operator: dict[str, list[Candidate]] = {}
    for option in options:
        by_operator.setdefault(option.operator.id, []).append(option)
    for group in by_operator.values():
        rng.shuffle(group)
    order = sorted(by_operator, key=lambda op: (usage.get(op, 0), rng.random()))
    used_files: set[str] = set()
    for op in order:
        if len(chosen) >= per_pr:
            break
        pick = next((c for c in by_operator[op] if c.path not in used_files), None)
        if pick is None:
            continue
        chosen.append(pick)
        used_files.add(pick.path)
        usage[op] = usage.get(op, 0) + 1
    return chosen


def build_cases(
    *,
    corpus_dir: Path = CORPUS_DIR,
    operators: list[Operator] | None = None,
    seed: int = DEFAULT_SEED,
    per_pr: int = 3,
    max_tokens: int = 60_000,
) -> BuildReport:
    operators = operators or load_operators()
    report = BuildReport()
    usage: dict[str, int] = {}
    for repo, number, path in corpus_diffs(corpus_dir):
        prefix = f"{repo}-pr{number}"
        full = parse_diff(path.read_text(encoding="utf-8"))
        reviewed = filter_diff(full)
        tokens = sum(estimate_tokens(render_file(f)) for f in reviewed.files)
        if not reviewed.files:
            report.skipped.append((prefix, "nothing reviewable after filters"))
            continue
        if tokens > max_tokens:
            report.skipped.append((prefix, f"too large ({tokens} tokens)"))
            continue
        report.cases.append(
            Case(
                id=f"{prefix}-clean",
                repo=repo,
                pr=number,
                kind="clean",
                diff=serialize_diff(full),
                tokens=tokens,
            )
        )
        rng = random.Random(f"{seed}:{prefix}")
        options = candidates(reviewed.diff, operators)
        for k, candidate in enumerate(pick_candidates(options, rng, usage, per_pr), start=1):
            mutated, label = apply(full, candidate)
            report.cases.append(
                Case(
                    id=f"{prefix}-m{k}",
                    repo=repo,
                    pr=number,
                    kind="mutated",
                    diff=serialize_diff(mutated),
                    labels=(label,),
                    tokens=tokens,
                )
            )
    return report


def write_cases(
    report: BuildReport, cases_dir: Path = CASES_DIR, index_path: Path = INDEX_PATH
) -> None:
    cases_dir.mkdir(parents=True, exist_ok=True)
    for stale in cases_dir.glob("*.json"):
        stale.unlink()
    for case in report.cases:
        (cases_dir / f"{case.id}.json").write_text(
            json.dumps(case.to_dict(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    index = {
        "seed": DEFAULT_SEED,
        "cases": [
            {
                "id": case.id,
                "kind": case.kind,
                "repo": case.repo,
                "pr": case.pr,
                "tokens": case.tokens,
                "digest": case.digest(),
                "labels": [label.to_dict() for label in case.labels],
            }
            for case in report.cases
        ],
        "skipped": [{"pr": pr, "reason": reason} for pr, reason in report.skipped],
    }
    index_path.write_text(json.dumps(index, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def load_cases(cases_dir: Path = CASES_DIR) -> list[Case]:
    return [
        Case.from_dict(json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(cases_dir.glob("*.json"))
    ]


def load_index(index_path: Path = INDEX_PATH) -> dict[str, Any]:
    return dict(json.loads(index_path.read_text(encoding="utf-8")))

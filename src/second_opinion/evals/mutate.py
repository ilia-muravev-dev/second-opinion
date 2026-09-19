"""Mutation operators: a small, declared catalogue of ways real code goes wrong, applied to one
added line of a real pull request so the eval set has exact ground truth."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from second_opinion.checks.base import is_test_path
from second_opinion.diff import Diff, DiffLine, FileDiff, Hunk, rebuild_file

OPERATORS_PATH = Path(__file__).resolve().parents[3] / "evals" / "operators.yaml"
SOURCE_LANGUAGES = {"python", "typescript", "javascript"}


@dataclass(frozen=True)
class Operator:
    id: str
    languages: frozenset[str]
    category: str
    severity: str
    pattern: re.Pattern[str]
    replace: str | None
    delete: bool
    insert: dict[str, str]  # language -> template, for insert-after operators
    guard: re.Pattern[str] | None
    test_files: bool
    description: str

    def applies_to(self, file: FileDiff, line: DiffLine) -> bool:
        if file.language not in self.languages:
            return False
        if is_test_path(file.path) != self.test_files:
            return False
        if self.guard is not None and self.guard.search(line.content):
            return False
        return self.pattern.search(line.content) is not None

    def mutate(self, content: str, language: str | None) -> str | None:
        """The mutated line, or None for a deletion."""
        if self.delete:
            return None
        if self.insert:
            template = self.insert.get(language or "", self.insert.get("default", ""))
            return self.pattern.sub(template, content, count=1)
        assert self.replace is not None
        return self.pattern.sub(self.replace, content, count=1)


@dataclass(frozen=True)
class Label:
    file: str
    line: int
    category: str
    severity: str
    operator: str
    description: str
    original: str
    mutated: str | None

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class Candidate:
    path: str
    hunk_index: int
    line_index: int
    operator: Operator


def load_operators(path: Path = OPERATORS_PATH) -> list[Operator]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    operators: list[Operator] = []
    for item in raw:
        insert: dict[str, str] = {}
        if item.get("insert_after"):
            insert["default"] = str(item["insert"])
            insert["typescript"] = str(item["insert"])
            insert["javascript"] = str(item["insert"])
            insert["python"] = str(item.get("insert_py", item["insert"]))
        delete = bool(item.get("delete", False))
        replace = item.get("replace")
        if not delete and not insert and replace is None:
            msg = f"operator {item['id']} needs replace, delete or insert"
            raise ValueError(msg)
        operators.append(
            Operator(
                id=str(item["id"]),
                languages=frozenset(item["languages"]),
                category=str(item["category"]),
                severity=str(item["severity"]),
                pattern=re.compile(str(item["pattern"])),
                replace=None if replace is None else str(replace),
                delete=delete,
                insert=insert,
                guard=re.compile(str(item["guard"])) if item.get("guard") else None,
                test_files=bool(item.get("test_files", False)),
                description=str(item["description"]),
            )
        )
    return operators


def candidates(diff: Diff, operators: list[Operator]) -> list[Candidate]:
    found: list[Candidate] = []
    for file in diff.files:
        if file.is_binary or file.language not in SOURCE_LANGUAGES:
            continue
        for h, hunk in enumerate(file.hunks):
            for i, line in enumerate(hunk.lines):
                if line.kind != "added" or not line.content.strip():
                    continue
                found.extend(
                    Candidate(file.path, h, i, op) for op in operators if op.applies_to(file, line)
                )
    return found


def apply(diff: Diff, candidate: Candidate) -> tuple[Diff, Label]:
    file = diff.file(candidate.path)
    if file is None:
        msg = f"{candidate.path} is not in the diff"
        raise ValueError(msg)
    hunks = list(file.hunks)
    hunk = hunks[candidate.hunk_index]
    lines = list(hunk.lines)
    target = lines[candidate.line_index]
    op = candidate.operator
    mutated = op.mutate(target.content, file.language)
    if op.delete:
        del lines[candidate.line_index]
        # the defect is an absence: point at the line that now precedes the gap
        previous = next(
            (line for line in reversed(lines[: candidate.line_index]) if line.kind != "removed"),
            None,
        )
    elif op.insert:
        assert mutated is not None
        lines.insert(candidate.line_index + 1, DiffLine("added", mutated, None, None))
    else:
        assert mutated is not None
        lines[candidate.line_index] = DiffLine("added", mutated, None, None)
    hunks[candidate.hunk_index] = Hunk(
        hunk.old_start, hunk.old_len, hunk.new_start, hunk.new_len, hunk.section, tuple(lines)
    )
    rebuilt = rebuild_file(file, hunks)
    new_hunk = rebuilt.hunks[candidate.hunk_index]
    if op.delete:
        label_line = (
            previous.new_no
            if previous is not None and previous.new_no is not None
            else new_hunk.new_start
        )
    elif op.insert:
        label_line = new_hunk.lines[candidate.line_index + 1].new_no or new_hunk.new_start
    else:
        label_line = new_hunk.lines[candidate.line_index].new_no or new_hunk.new_start
    files = tuple(rebuilt if f.path == file.path else f for f in diff.files)
    label = Label(
        file=file.path,
        line=label_line,
        category=op.category,
        severity=op.severity,
        operator=op.id,
        description=op.description,
        original=target.content,
        mutated=mutated if not op.insert else f"{target.content}\n{mutated}",
    )
    return Diff(files), label

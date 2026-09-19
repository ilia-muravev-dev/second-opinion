"""Runs the review over the eval set and keeps a row per case in a run file that survives
interruptions: a daily request cap stops the run cleanly, and the next invocation continues where
it left off. The run file is what the report and the comparison table read."""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from second_opinion.config import Settings
from second_opinion.evals.dataset import Case
from second_opinion.evals.match import score_case
from second_opinion.llm.cassette import CassetteMode
from second_opinion.llm.provider import LLMError, LLMProvider
from second_opinion.pipeline import run_review

ROOT = Path(__file__).resolve().parents[3]
RUNS_DIR = ROOT / "evals" / "runs"
CASSETTES_DIR = ROOT / "evals" / "cassettes"


def slugify(model: str, prompt_version: str) -> str:
    model_slug = re.sub(r"[^a-z0-9.]+", "-", model.lower()).strip("-")
    return f"{model_slug}--{prompt_version}"


def run_path(slug: str, runs_dir: Path = RUNS_DIR) -> Path:
    return runs_dir / f"{slug}.jsonl"


def load_run(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        latest[row["case_id"]] = row  # a re-run of a case replaces the earlier row
    return list(latest.values())


@dataclass
class RunOutcome:
    slug: str
    done: int
    skipped: int
    stopped_by: str | None
    elapsed_s: float


def _review_case(
    case: Case, settings: Settings, provider: LLMProvider, cassette_mode: CassetteMode
) -> dict[str, Any]:
    case_started = time.perf_counter()
    run = run_review(case.diff, settings, provider, case_id=case.id)
    score = score_case(case.id, case.kind, list(case.labels), run.report.findings)
    return {
        "case_id": case.id,
        "kind": case.kind,
        "repo": case.repo,
        "pr": case.pr,
        "labels": [label.to_dict() for label in case.labels],
        "model": settings.model,
        "prompt": settings.prompt_version,
        "provider": provider.name,
        "cassette": cassette_mode,
        "requests": run.report.requests,
        "usage": run.report.usage.__dict__,
        "cost_usd": run.report.cost_usd,
        "errors": run.report.errors,
        "verified": run.report.verified,
        "rejected": run.report.rejected,
        "elapsed_s": round(time.perf_counter() - case_started, 1),
        "findings": [
            {
                "source": f.source,
                "check": f.check,
                "file": f.file,
                "line": f.line,
                "end_line": f.end_line,
                "severity": f.severity,
                "category": f.category,
                "title": f.title,
                "confidence": f.confidence,
                "verdict": f.verdict,
            }
            for f in run.report.findings
        ],
        "score": score.__dict__,
    }


def run_cases(
    cases: list[Case],
    settings: Settings,
    provider: LLMProvider,
    *,
    runs_dir: Path = RUNS_DIR,
    resume: bool = True,
    on_case: Callable[[str, dict[str, Any]], None] | None = None,
    cassette_mode: CassetteMode = "off",
    workers: int = 1,
    skip_missing: bool = False,
) -> RunOutcome:
    """Cases run in order (or `workers` at a time); rows are appended as they finish. The first
    rate limit or auth failure stops the run: cases still in flight finish, no new ones start.
    With `skip_missing`, a case without a recording is skipped instead of stopping a replay."""
    slug = slugify(settings.model, settings.prompt_version)
    path = run_path(slug, runs_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)
    already = {row["case_id"] for row in load_run(path)} if resume else set()
    started = time.perf_counter()
    todo = [case for case in cases if case.id not in already]
    skipped = len(cases) - len(todo)
    done = 0
    stopped_by: str | None = None
    lock = threading.Lock()
    stop = threading.Event()

    def work(case: Case) -> None:
        nonlocal done, skipped, stopped_by
        if stop.is_set():
            return
        try:
            row = _review_case(case, settings, provider, cassette_mode)
        except LLMError as error:
            if skip_missing and error.kind == "cassette_miss":
                with lock:
                    skipped += 1
                return
            with lock:
                if stopped_by is None:
                    stopped_by = f"{error.kind}: {error}"
            stop.set()
            return
        with lock, path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            done += 1
            if on_case is not None:
                on_case(case.id, row)

    if workers <= 1:
        for case in todo:
            work(case)
            if stop.is_set():
                break
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(work, todo))
    compact(path)
    return RunOutcome(slug, done, skipped, stopped_by, round(time.perf_counter() - started, 1))


def compact(path: Path) -> None:
    """One row per case, the latest, in case order: a re-run does not grow the file forever."""
    rows = load_run(path)
    if rows:
        rows.sort(key=lambda row: str(row["case_id"]))
        path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
        )

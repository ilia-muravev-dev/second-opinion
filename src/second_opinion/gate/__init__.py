"""The eval gate: CI replays the recorded responses of the baseline run and fails when the
scoring of that run drops below the committed baseline — so a change to the matcher, the merge
rules or the checks cannot quietly make the reviewer look worse (or better) than it is."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from second_opinion.evals.metrics import RunMetrics, compute
from second_opinion.evals.runner import ROOT, load_run, run_path

BASELINE_PATH = ROOT / "evals" / "baseline.json"


@dataclass(frozen=True)
class Baseline:
    slug: str
    cases: int
    recall_min: float
    precision_min: float
    false_positives_per_clean_max: float

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Baseline:
        return cls(
            slug=str(data["slug"]),
            cases=int(data["cases"]),
            recall_min=float(data["recall_min"]),
            precision_min=float(data["precision_min"]),
            false_positives_per_clean_max=float(data["false_positives_per_clean_max"]),
        )


def write_baseline(slug: str, *, margin: float = 0.02, path: Path = BASELINE_PATH) -> Baseline:
    rows = load_run(run_path(slug))
    if not rows:
        msg = f"no run file for {slug}"
        raise FileNotFoundError(msg)
    m = compute(rows)
    baseline = Baseline(
        slug=slug,
        cases=m.cases,
        recall_min=round(max(0.0, m.recall - margin), 4),
        precision_min=round(max(0.0, m.precision - margin), 4),
        false_positives_per_clean_max=round(m.false_positives_per_clean + 0.1, 4),
    )
    path.write_text(json.dumps(baseline.to_dict(), indent=1) + "\n", encoding="utf-8")
    return baseline


def load_baseline(path: Path = BASELINE_PATH) -> Baseline:
    return Baseline.from_dict(json.loads(path.read_text(encoding="utf-8")))


def check_against(m: RunMetrics, baseline: Baseline) -> list[str]:
    """Human-readable failures; empty means the gate passes."""
    failures: list[str] = []
    if m.cases < baseline.cases:
        failures.append(f"only {m.cases} cases scored, baseline has {baseline.cases}")
    if m.recall < baseline.recall_min:
        failures.append(f"recall {m.recall:.3f} < {baseline.recall_min:.3f}")
    if m.precision < baseline.precision_min:
        failures.append(f"precision {m.precision:.3f} < {baseline.precision_min:.3f}")
    if m.false_positives_per_clean > baseline.false_positives_per_clean_max:
        failures.append(
            f"false positives per clean PR {m.false_positives_per_clean:.2f} > "
            f"{baseline.false_positives_per_clean_max:.2f}"
        )
    return failures

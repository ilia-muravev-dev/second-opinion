"""From per-case scores to the numbers in the table."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from second_opinion.evals.stats import interval, pct


@dataclass
class RunMetrics:
    cases: int
    mutated_cases: int
    clean_cases: int
    labels: int
    found: int
    found_by_checks: int
    model_findings_on_mutated: int
    model_hits: int
    unlabelled_on_mutated: int
    model_findings_on_clean: int
    category_agreed: int
    requests: int
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    errors: int
    by_operator: dict[str, tuple[int, int]] = field(default_factory=dict)
    by_category: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def recall(self) -> float:
        return self.found / self.labels if self.labels else 0.0

    @property
    def precision(self) -> float:
        """Of the model's findings on mutated cases, the share that hit the planted defect."""
        return (
            self.model_hits / self.model_findings_on_mutated
            if self.model_findings_on_mutated
            else 0.0
        )

    @property
    def false_positives_per_clean(self) -> float:
        return self.model_findings_on_clean / self.clean_cases if self.clean_cases else 0.0

    @property
    def unlabelled_per_mutated(self) -> float:
        return self.unlabelled_on_mutated / self.mutated_cases if self.mutated_cases else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            **{k: v for k, v in self.__dict__.items() if k not in {"by_operator", "by_category"}},
            "recall": self.recall,
            "precision": self.precision,
            "false_positives_per_clean": self.false_positives_per_clean,
            "unlabelled_per_mutated": self.unlabelled_per_mutated,
            "by_operator": {k: list(v) for k, v in self.by_operator.items()},
            "by_category": {k: list(v) for k, v in self.by_category.items()},
        }


def compute(records: list[dict[str, Any]]) -> RunMetrics:
    """`records` are the run file's rows: case metadata, score, usage."""
    by_operator: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    by_category: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    m = RunMetrics(
        cases=len(records),
        mutated_cases=0,
        clean_cases=0,
        labels=0,
        found=0,
        found_by_checks=0,
        model_findings_on_mutated=0,
        model_hits=0,
        unlabelled_on_mutated=0,
        model_findings_on_clean=0,
        category_agreed=0,
        requests=0,
        input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
        errors=0,
    )
    for record in records:
        score = record["score"]
        usage = record.get("usage", {})
        m.requests += int(record.get("requests", 0))
        m.input_tokens += (
            int(usage.get("input_tokens", 0))
            + int(usage.get("cache_read_tokens", 0))
            + int(usage.get("cache_write_tokens", 0))
        )
        m.output_tokens += int(usage.get("output_tokens", 0))
        cost = record.get("cost_usd")
        if cost is None:
            m.cost_usd = None
        elif m.cost_usd is not None:
            m.cost_usd += float(cost)
        m.errors += len(record.get("errors", []))
        if record["kind"] == "clean":
            m.clean_cases += 1
            m.model_findings_on_clean += int(score["model_findings"])
            continue
        m.mutated_cases += 1
        m.labels += int(score["labels"])
        m.found += int(score["found"])
        m.found_by_checks += int(score["check_hits"])
        m.model_findings_on_mutated += int(score["model_findings"])
        m.model_hits += int(score["model_hits"])
        m.unlabelled_on_mutated += int(score["unlabelled_model"])
        m.category_agreed += int(score["category_agreed"])
        for label in record.get("labels", []):
            by_operator[label["operator"]][1] += 1
            by_category[label["category"]][1] += 1
        for hit in score.get("found_by", []):
            by_operator[hit["operator"]][0] += 1
            label = next(
                (lb for lb in record.get("labels", []) if lb["operator"] == hit["operator"]), None
            )
            if label:
                by_category[label["category"]][0] += 1
    m.by_operator = {k: (v[0], v[1]) for k, v in sorted(by_operator.items())}
    m.by_category = {k: (v[0], v[1]) for k, v in sorted(by_category.items())}
    return m


def summary_line(m: RunMetrics) -> str:
    return (
        f"recall {pct(m.recall)} ({m.found}/{m.labels}, 95% CI {interval(m.found, m.labels)}), "
        f"precision {pct(m.precision)} ({m.model_hits}/{m.model_findings_on_mutated}), "
        f"{m.false_positives_per_clean:.2f} model findings per clean PR"
    )

import json
from pathlib import Path

from second_opinion.evals.metrics import compute
from second_opinion.gate import Baseline, check_against, load_baseline, write_baseline


def test_baseline_round_trip_and_checks(tmp_path: Path, monkeypatch) -> None:
    rows = [
        {
            "case_id": "a-m1",
            "kind": "mutated",
            "labels": [{"operator": "op", "category": "correctness"}],
            "requests": 1,
            "usage": {},
            "cost_usd": 0.0,
            "errors": [],
            "score": {
                "labels": 1,
                "found": 1,
                "model_findings": 2,
                "model_hits": 1,
                "check_findings": 0,
                "check_hits": 0,
                "unlabelled_model": 1,
                "category_agreed": 1,
                "found_by": [{"operator": "op"}],
            },
        },
        {
            "case_id": "a-clean",
            "kind": "clean",
            "labels": [],
            "requests": 1,
            "usage": {},
            "cost_usd": 0.0,
            "errors": [],
            "score": {
                "labels": 0,
                "found": 0,
                "model_findings": 1,
                "model_hits": 0,
                "check_findings": 0,
                "check_hits": 0,
                "unlabelled_model": 1,
                "category_agreed": 0,
                "found_by": [],
            },
        },
    ]
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "m--v1.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    monkeypatch.setattr("second_opinion.gate.run_path", lambda slug: runs / f"{slug}.jsonl")
    baseline = write_baseline("m--v1", margin=0.05, path=tmp_path / "baseline.json")
    assert baseline == load_baseline(tmp_path / "baseline.json")
    assert (baseline.cases, baseline.recall_min, baseline.precision_min) == (2, 0.95, 0.45)
    assert baseline.false_positives_per_clean_max == 1.1

    metrics = compute(rows)
    assert check_against(metrics, baseline) == []
    worse = Baseline(
        "m--v1", cases=3, recall_min=1.0, precision_min=0.9, false_positives_per_clean_max=0.5
    )
    failures = check_against(metrics, worse)
    assert len(failures) == 3
    assert failures[0].startswith("only 2 cases")

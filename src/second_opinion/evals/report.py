"""The markdown a run leaves behind under docs/evals/, and the table that compares runs."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from second_opinion.evals.metrics import RunMetrics, compute, summary_line
from second_opinion.evals.runner import ROOT, load_run, run_path
from second_opinion.evals.stats import interval, pct

DOCS_DIR = ROOT / "docs" / "evals"


def _row(metric: str, value: str) -> str:
    return f"| {metric} | {value} |"


def render_report(slug: str, rows: list[dict[str, Any]], m: RunMetrics) -> str:
    first = rows[0] if rows else {}
    model = str(first.get("model", "?"))
    prompt = str(first.get("prompt", "?"))
    provider = str(first.get("provider", "?"))
    when = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    cost = "$" + format(m.cost_usd, ".4f") if m.cost_usd is not None else "not reported"
    per_case = f" ({m.requests / m.cases:.1f} per case)" if m.cases else ""
    lines = [
        f"# Eval run `{slug}`",
        "",
        f"Model `{model}` via {provider}, prompt `{prompt}`, {m.cases} cases "
        f"({m.mutated_cases} with one planted defect each, {m.clean_cases} clean), "
        f"written {when} by `second-opinion eval report`.",
        "",
        f"**{summary_line(m)}**",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        _row(
            "Recall (planted defects found)",
            f"{pct(m.recall)} — {m.found}/{m.labels}, 95% CI {interval(m.found, m.labels)}",
        ),
        _row("… of which found by a deterministic check", str(m.found_by_checks)),
        _row(
            "Precision (model findings on mutated PRs that hit the defect)",
            f"{pct(m.precision)} — {m.model_hits}/{m.model_findings_on_mutated}",
        ),
        _row("Unlabelled model findings per mutated PR", f"{m.unlabelled_per_mutated:.2f}"),
        _row(
            "Model findings per clean PR (false positives, by construction)",
            f"{m.false_positives_per_clean:.2f} — {m.model_findings_on_clean} over {m.clean_cases}",
        ),
        _row("Category agreed, of found", f"{m.category_agreed}/{m.found}"),
        _row("Requests", f"{m.requests}{per_case}"),
        _row("Tokens in / out", f"{m.input_tokens:,} / {m.output_tokens:,}"),
        _row("Cost", cost),
        _row("Cases with a model error", str(m.errors)),
        "",
        "Unlabelled findings on mutated PRs are not counted as wrong: the original pull requests "
        "may carry real issues. A sample should be read by hand before drawing conclusions from "
        "precision alone.",
        "",
        "## By operator",
        "",
        "| Operator | Found | Of |",
        "| --- | ---: | ---: |",
    ]
    lines += [f"| `{op}` | {found} | {total} |" for op, (found, total) in m.by_operator.items()]
    lines += ["", "## By category", "", "| Category | Found | Of |", "| --- | ---: | ---: |"]
    lines += [f"| {cat} | {found} | {total} |" for cat, (found, total) in m.by_category.items()]
    misses = [
        (row["case_id"], label["operator"], label["file"], label["line"])
        for row in rows
        if row["kind"] == "mutated"
        for label in row["labels"]
        if not any(hit["operator"] == label["operator"] for hit in row["score"].get("found_by", []))
    ]
    if misses:
        lines += ["", "## Missed", "", "| Case | Operator | Where |", "| --- | --- | --- |"]
        lines += [f"| `{case}` | `{op}` | `{file}:{line}` |" for case, op, file, line in misses]
    return "\n".join(lines) + "\n"


def write_report(slug: str, *, docs_dir: Path = DOCS_DIR) -> tuple[Path, RunMetrics]:
    rows = load_run(run_path(slug))
    if not rows:
        msg = f"no run file for {slug}"
        raise FileNotFoundError(msg)
    m = compute(rows)
    docs_dir.mkdir(parents=True, exist_ok=True)
    path = docs_dir / f"{slug}.md"
    path.write_text(render_report(slug, rows, m), encoding="utf-8")
    (docs_dir / f"{slug}.json").write_text(
        json.dumps(m.to_dict(), indent=1) + "\n", encoding="utf-8"
    )
    return path, m


def render_comparison(slugs: list[str]) -> str:
    lines = [
        "| Run | Cases | Recall | Precision | FP / clean PR | Unlabelled / mutated PR | "
        "Requests | Tokens in / out | Cost |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |",
    ]
    for slug in slugs:
        rows = load_run(run_path(slug))
        if not rows:
            lines.append(f"| `{slug}` | no run | | | | | | | |")
            continue
        m = compute(rows)
        cost = f"${m.cost_usd:.2f}" if m.cost_usd is not None else "n/a"
        lines.append(
            f"| `{slug}` | {m.cases} | {pct(m.recall)} ({m.found}/{m.labels}) | "
            f"{pct(m.precision)} ({m.model_hits}/{m.model_findings_on_mutated}) | "
            f"{m.false_positives_per_clean:.2f} | {m.unlabelled_per_mutated:.2f} | {m.requests} | "
            f"{m.input_tokens:,} / {m.output_tokens:,} | {cost} |"
        )
    return "\n".join(lines) + "\n"

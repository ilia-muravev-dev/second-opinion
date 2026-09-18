"""The eval set and the harness that scores the reviewer against it."""

from second_opinion.evals.dataset import Case, build_cases, load_cases, load_index, write_cases
from second_opinion.evals.match import hits, score_case
from second_opinion.evals.metrics import RunMetrics, compute, summary_line
from second_opinion.evals.mutate import Label, Operator, apply, candidates, load_operators
from second_opinion.evals.report import render_comparison, write_report
from second_opinion.evals.runner import RunOutcome, load_run, run_cases, run_path, slugify

__all__ = [
    "Case",
    "Label",
    "Operator",
    "RunMetrics",
    "RunOutcome",
    "apply",
    "build_cases",
    "candidates",
    "compute",
    "hits",
    "load_cases",
    "load_index",
    "load_operators",
    "load_run",
    "render_comparison",
    "run_cases",
    "run_path",
    "score_case",
    "slugify",
    "summary_line",
    "write_cases",
    "write_report",
]

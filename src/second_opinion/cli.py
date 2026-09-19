"""The command line: `second-opinion review`, `checks`, `eval …`, `gate …`. Commands land with the
pull requests that implement them; the skeleton only knows how to introduce itself."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from second_opinion import __version__
from second_opinion.checks import run_checks
from second_opinion.config import Settings, load_settings
from second_opinion.diff import filter_diff, parse_diff
from second_opinion.evals import (
    build_cases,
    compute,
    load_cases,
    load_index,
    load_run,
    render_comparison,
    run_cases,
    run_path,
    slugify,
    summary_line,
    write_cases,
    write_report,
)
from second_opinion.evals.dataset import CASES_DIR, INDEX_PATH
from second_opinion.evals.runner import CASSETTES_DIR, ROOT
from second_opinion.findings import SEVERITY_ORDER, Finding
from second_opinion.gate import BASELINE_PATH, check_against, load_baseline, write_baseline
from second_opinion.github import GitHubClient, event_pull_number, post_review, repo_from_env
from second_opinion.llm import LLMError, make_provider
from second_opinion.pipeline import ReviewRun, run_review
from second_opinion.report import render_markdown

RUNS_TMP = ROOT / "evals" / "runs" / ".replay"

app = typer.Typer(
    name="second-opinion",
    help="A pull-request reviewer that measures itself.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def main() -> None:
    """A pull-request reviewer that measures itself."""


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(f"second-opinion {__version__}")


DiffOption = Annotated[
    Path, typer.Option("--diff", exists=True, dir_okay=False, help="A unified diff file")
]
OptionalDiffOption = Annotated[
    Path | None, typer.Option("--diff", exists=True, dir_okay=False, help="A unified diff file")
]
JsonOption = Annotated[bool, typer.Option("--json", help="Print findings as JSON")]
ProviderOption = Annotated[
    str | None, typer.Option("--provider", help="anthropic | openai | fake (default: SO_PROVIDER)")
]
ModelOption = Annotated[str | None, typer.Option("--model", help="Model id (default: SO_MODEL)")]
PromptOption = Annotated[
    str | None, typer.Option("--prompt", help="Prompt version (default: SO_PROMPT_VERSION)")
]


def settings_from(provider: str | None, model: str | None, prompt: str | None) -> Settings:
    overrides: dict[str, object] = {}
    if provider:
        overrides["provider"] = provider
    if model:
        overrides["model"] = model
    if prompt:
        overrides["prompt_version"] = prompt
    return load_settings(**overrides)


@app.command()
def review(
    diff: OptionalDiffOption = None,
    pr: Annotated[int | None, typer.Option("--pr", help="Pull request number")] = None,
    repo: Annotated[
        str | None, typer.Option("--repo", help="owner/name (default: $GITHUB_REPOSITORY)")
    ] = None,
    post: Annotated[str, typer.Option("--post", help="review | summary | none")] = "none",
    fail_on: Annotated[str, typer.Option("--fail-on", help="none | high | medium | low")] = "none",
    provider: ProviderOption = None,
    model: ModelOption = None,
    prompt: PromptOption = None,
    title: Annotated[str | None, typer.Option(help="Pull request title, for context")] = None,
    checks_only: Annotated[bool, typer.Option("--checks-only", help="Skip the model")] = False,
    as_json: JsonOption = False,
) -> None:
    """Review a diff file or a pull request: deterministic checks, then the model.

    With --pr the diff comes from GitHub and --post decides what goes back: inline comments plus
    a summary (review), the summary only, or nothing (the default; markdown on stdout)."""
    settings = settings_from(provider, model, prompt)
    if post not in {"review", "summary", "none"}:
        raise typer.BadParameter("--post must be review, summary or none")
    if fail_on not in {"none", *SEVERITY_ORDER}:
        raise typer.BadParameter("--fail-on must be none, high, medium or low")
    llm = None if checks_only else make_provider(settings)
    if diff is not None:
        run = guarded_review(
            diff.read_text(encoding="utf-8"), settings, llm, title=title, checks_only=checks_only
        )
    else:
        number = pr or event_pull_number()
        slug = repo.split("/", 1) if repo else repo_from_env()
        if number is None or slug is None:
            raise typer.BadParameter("give --diff, or --pr and --repo (or run inside Actions)")
        token = settings.github_token or os.environ.get("GITHUB_TOKEN")
        if not token:
            raise typer.BadParameter("a GitHub token is required: SO_GITHUB_TOKEN or GITHUB_TOKEN")
        client = GitHubClient(token)
        pull = client.get_pull(slug[0], slug[1], number)
        run = guarded_review(
            client.get_diff(slug[0], slug[1], number),
            settings,
            llm,
            title=pull.title,
            description=pull.body,
            checks_only=checks_only,
        )
        if post != "none":
            outcome = post_review(client, pull, run.report, mode=post)
            typer.echo(
                f"posted: {outcome.inline_posted} inline, "
                f"{outcome.inline_skipped_seen} already there, summary "
                f"{'updated' if outcome.summary_updated else 'not posted'}",
                err=True,
            )
    emit(run, as_json)
    write_outputs(run)
    if fail_on != "none" and any(
        SEVERITY_ORDER[f.severity] <= SEVERITY_ORDER[fail_on] for f in run.report.findings
    ):
        raise typer.Exit(code=2)


def guarded_review(
    diff_text: str,
    settings: Settings,
    llm: object | None,
    *,
    title: str | None = None,
    description: str | None = None,
    checks_only: bool = False,
) -> ReviewRun:
    """A rate limit or a bad key must not fail the pull request's check: the deterministic
    findings are still reported, with a note that the model did not run."""
    try:
        return run_review(
            diff_text,
            settings,
            llm,  # type: ignore[arg-type]
            title=title,
            description=description,
            checks_only=checks_only,
        )
    except LLMError as error:
        if error.kind not in {"rate_limit", "auth"}:
            raise
        typer.echo(f"model review skipped: {error}", err=True)
        run = run_review(diff_text, settings, None, title=title, description=description)
        run.report.errors.append(f"the model did not run ({error.kind}): {error}")
        return run


def emit(run: ReviewRun, as_json: bool) -> None:
    if as_json:
        typer.echo(
            json.dumps(
                {
                    "findings": [f.model_dump() for f in run.report.findings],
                    "summaries": run.report.summaries,
                    "skipped": [s.__dict__ for s in run.report.skipped],
                    "requests": run.report.requests,
                    "usage": run.report.usage.__dict__,
                    "cost_usd": run.report.cost_usd,
                    "errors": run.report.errors,
                },
                indent=2,
            )
        )
        return
    typer.echo(render_markdown(run.report), nl=False)


def write_outputs(run: ReviewRun) -> None:
    """Action outputs, when running inside GitHub Actions."""
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(f"findings={len(run.report.findings)}\n")
        handle.write(f"high={sum(1 for f in run.report.findings if f.severity == 'high')}\n")
        handle.write(f"requests={run.report.requests}\n")
        handle.write(f"cost_usd={run.report.cost_usd if run.report.cost_usd is not None else ''}\n")


@app.command()
def checks(diff: DiffOption, as_json: JsonOption = False) -> None:
    """Run the deterministic checks on a diff, without a model."""
    parsed = parse_diff(diff.read_text(encoding="utf-8"))
    findings = run_checks(filter_diff(parsed), parsed)
    if as_json:
        typer.echo(json.dumps([f.model_dump() for f in findings], indent=2))
        return
    print_findings(findings)


def print_findings(findings: list[Finding]) -> None:
    console = Console()
    if not findings:
        console.print("[green]no findings[/green]")
        return
    table = Table(show_lines=False)
    for column in ("severity", "where", "title", "source"):
        table.add_column(column)
    for f in findings:
        where = f"{f.file}:{f.line}" if f.line else (f.file or "(pull request)")
        table.add_row(f.severity, where, f.title, f.check or f.source)
    console.print(table)


eval_app = typer.Typer(
    help="Build the eval set, run it, report and compare runs.", no_args_is_help=True
)
app.add_typer(eval_app, name="eval")


@eval_app.command("build")
def eval_build(
    per_pr: Annotated[int, typer.Option(help="Mutated copies per pull request")] = 3,
    check: Annotated[bool, typer.Option("--check", help="Fail if the index would change")] = False,
) -> None:
    """Generate the cases from the corpus and the operator catalogue (deterministic)."""
    report = build_cases(per_pr=per_pr)
    if check:
        previous = load_index(INDEX_PATH) if INDEX_PATH.exists() else {"cases": []}
        fresh = {c.id: c.digest() for c in report.cases}
        old = {c["id"]: c["digest"] for c in previous["cases"]}
        if fresh != old:
            changed = sorted(set(fresh) ^ set(old) | {k for k in fresh if old.get(k) != fresh[k]})
            typer.echo(f"the eval set drifted: {', '.join(changed[:10])}", err=True)
            raise typer.Exit(code=1)
    write_cases(report)
    mutated = sum(1 for c in report.cases if c.kind == "mutated")
    typer.echo(
        f"{len(report.cases)} cases ({mutated} mutated) in {CASES_DIR}; index {INDEX_PATH.name}"
    )
    for pr, reason in report.skipped:
        typer.echo(f"  skipped {pr}: {reason}")


@eval_app.command("run")
def eval_run(
    prompt: PromptOption = None,
    provider: ProviderOption = None,
    model: ModelOption = None,
    cassette: Annotated[str, typer.Option(help="off | record | replay")] = "record",
    limit: Annotated[int | None, typer.Option(help="Run at most this many cases")] = None,
    only: Annotated[list[str] | None, typer.Option("--only", help="Case ids")] = None,
    kind: Annotated[str | None, typer.Option(help="mutated | clean")] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Re-run cases already in the run file")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask before spending")] = False,
    workers: Annotated[int, typer.Option(help="Cases reviewed at a time")] = 1,
) -> None:
    """Review every case (resumable) and append results to evals/runs/<model>--<prompt>.jsonl."""
    settings = settings_from(provider, model, prompt)
    if cassette not in {"off", "record", "replay"}:
        raise typer.BadParameter("--cassette must be off, record or replay")
    if not CASES_DIR.exists() or not any(CASES_DIR.glob("*.json")):
        write_cases(build_cases())
    cases = load_cases()
    if kind:
        cases = [c for c in cases if c.kind == kind]
    if only:
        wanted = set(only)
        cases = [c for c in cases if c.id in wanted]
    if limit is not None:
        cases = cases[:limit]
    llm = make_provider(settings, cassette_dir=CASSETTES_DIR, cassette_mode=cassette)  # type: ignore[arg-type]
    if settings.provider != "fake" and cassette != "replay" and not yes:
        typer.confirm(
            f"{len(cases)} cases on {settings.provider}/{settings.model}, prompt "
            f"{settings.prompt_version}; requests will be spent. Continue?",
            abort=True,
        )

    def progress(case_id: str, row: dict[str, object]) -> None:
        score = row["score"]
        assert isinstance(score, dict)
        typer.echo(
            f"  {case_id:<34} {row['kind']:<8} found {score['found']}/{score['labels']} "
            f"model {score['model_findings']} req {row['requests']} {row['elapsed_s']}s"
        )

    outcome = run_cases(
        cases,
        settings,
        llm,
        resume=not force,
        on_case=progress,
        cassette_mode=cassette,  # type: ignore[arg-type]
        workers=max(1, workers),
    )
    typer.echo(
        f"run {outcome.slug}: {outcome.done} done, {outcome.skipped} already there, "
        f"{outcome.elapsed_s}s"
    )
    if outcome.stopped_by:
        typer.echo(f"stopped early — {outcome.stopped_by}. Run again later to resume.", err=True)
    if outcome.done or outcome.skipped:
        path, metrics = write_report(outcome.slug)
        typer.echo(summary_line(metrics))
        typer.echo(f"report: {path}")


@eval_app.command("report")
def eval_report(slug: Annotated[str, typer.Argument(help="<model-slug>--<prompt>")]) -> None:
    """Re-render docs/evals/<slug>.md from the run file."""
    path, metrics = write_report(slug)
    typer.echo(summary_line(metrics))
    typer.echo(f"report: {path}")


@eval_app.command("compare")
def eval_compare(
    slugs: Annotated[list[str], typer.Argument(help="Run slugs, in table order")],
) -> None:
    """A markdown table comparing runs (paste into the README)."""
    typer.echo(render_comparison(slugs), nl=False)


@eval_app.command("slug")
def eval_slug(model: ModelOption = None, prompt: PromptOption = None) -> None:
    """Print the run slug for a model and prompt (what `report` and `compare` take)."""
    settings = settings_from(None, model, prompt)
    typer.echo(slugify(settings.model, settings.prompt_version))


gate_app = typer.Typer(help="The eval gate CI runs on replayed responses.", no_args_is_help=True)
app.add_typer(gate_app, name="gate")


@gate_app.command("write")
def gate_write(
    slug: Annotated[str, typer.Argument(help="The run to become the baseline")],
    margin: Annotated[float, typer.Option(help="Allowed drop in recall/precision")] = 0.02,
) -> None:
    """Write evals/baseline.json from a run file."""
    baseline = write_baseline(slug, margin=margin)
    typer.echo(f"baseline {baseline.slug}: {json.dumps(baseline.to_dict())} -> {BASELINE_PATH}")


@gate_app.command("check")
def gate_check(
    replay: Annotated[bool, typer.Option(help="Re-score the baseline run from cassettes")] = True,
) -> None:
    """Replay the baseline run from recorded responses and compare with the baseline."""
    baseline = load_baseline()
    model, prompt = baseline.slug.rsplit("--", 1)
    if replay:
        cases = load_cases() if CASES_DIR.exists() and any(CASES_DIR.glob("*.json")) else []
        if not cases:
            write_cases(build_cases())
            cases = load_cases()
        rows = load_run(run_path(baseline.slug))
        model = str(rows[0]["model"]) if rows else model
        settings = load_settings(provider="openai", model=model, prompt_version=prompt)
        llm = make_provider(settings, cassette_dir=CASSETTES_DIR, cassette_mode="replay")
        outcome = run_cases(
            cases, settings, llm, runs_dir=RUNS_TMP, resume=False, skip_missing=True
        )
        if outcome.stopped_by:
            typer.echo(f"gate: replay stopped — {outcome.stopped_by}", err=True)
            raise typer.Exit(code=1)
        metrics = compute(load_run(run_path(outcome.slug, RUNS_TMP)))
    else:
        metrics = compute(load_run(run_path(baseline.slug)))
    failures = check_against(metrics, baseline)
    typer.echo(summary_line(metrics))
    if failures:
        for failure in failures:
            typer.echo(f"gate: {failure}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"gate: ok against {baseline.slug}")

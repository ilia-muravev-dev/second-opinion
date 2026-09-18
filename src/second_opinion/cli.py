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
from second_opinion.findings import SEVERITY_ORDER, Finding
from second_opinion.github import GitHubClient, event_pull_number, post_review, repo_from_env
from second_opinion.llm import LLMError, make_provider
from second_opinion.pipeline import ReviewRun, run_review
from second_opinion.report import render_markdown

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

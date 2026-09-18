"""The command line: `second-opinion review`, `checks`, `eval …`, `gate …`. Commands land with the
pull requests that implement them; the skeleton only knows how to introduce itself."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from second_opinion import __version__
from second_opinion.checks import run_checks
from second_opinion.config import Settings, load_settings
from second_opinion.diff import filter_diff, parse_diff
from second_opinion.findings import Finding
from second_opinion.llm import make_provider
from second_opinion.pipeline import run_review
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
    diff: DiffOption,
    provider: ProviderOption = None,
    model: ModelOption = None,
    prompt: PromptOption = None,
    title: Annotated[str | None, typer.Option(help="Pull request title, for context")] = None,
    checks_only: Annotated[bool, typer.Option("--checks-only", help="Skip the model")] = False,
    as_json: JsonOption = False,
) -> None:
    """Review a unified diff: deterministic checks, then the model. Markdown on stdout."""
    settings = settings_from(provider, model, prompt)
    llm = None if checks_only else make_provider(settings)
    run = run_review(
        diff.read_text(encoding="utf-8"), settings, llm, title=title, checks_only=checks_only
    )
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

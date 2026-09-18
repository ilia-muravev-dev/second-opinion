"""The command line: `second-opinion review`, `checks`, `eval …`, `gate …`. Commands land with the
pull requests that implement them; the skeleton only knows how to introduce itself."""

from __future__ import annotations

import typer

from second_opinion import __version__

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

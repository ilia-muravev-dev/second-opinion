from typer.testing import CliRunner

from second_opinion import __version__
from second_opinion.cli import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_checks_command_prints_findings(tmp_path) -> None:
    diff = tmp_path / "x.diff"
    diff.write_text(
        "diff --git a/src/a.ts b/src/a.ts\nnew file mode 100644\n--- /dev/null\n+++ b/src/a.ts\n"
        "@@ -0,0 +1,1 @@\n+debugger;\n"
    )
    result = runner.invoke(app, ["checks", "--diff", str(diff)])
    assert result.exit_code == 0
    assert "Breakpoint left in the code" in result.output
    as_json = runner.invoke(app, ["checks", "--diff", str(diff), "--json"])
    assert as_json.exit_code == 0
    assert '"check": "debug_statements"' in as_json.output

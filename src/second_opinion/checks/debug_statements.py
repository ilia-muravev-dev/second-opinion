"""Debugging left behind: breakpoints, `debugger`, `console.log` in source, `print` in library
code (not in CLIs or scripts, where printing is the job)."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from second_opinion.checks.base import Check, CheckInput, finding, is_test_path
from second_opinion.findings import Finding

BREAKPOINTS = re.compile(r"\b(?:breakpoint\(\)|pdb\.set_trace\(\)|debugger;?)\s*$|\bdebugger\b")
CONSOLE = re.compile(r"\bconsole\.(?:log|debug|trace)\(")
PRINT = re.compile(r"^\s*print\(")
COMMENT = re.compile(r"^\s*(?://|#|\*)")
CLI_NAMES = {"cli.py", "__main__.py", "main.py", "cli.ts", "main.ts", "worker.ts", "seed.ts"}
SCRIPT_DIRS = ("scripts/", "bench/", "tools/", "examples/", "docs/")


def _is_script(path: str) -> bool:
    name = PurePosixPath(path).name
    return name in CLI_NAMES or any(part in path for part in SCRIPT_DIRS)


def run(inputs: CheckInput) -> list[Finding]:
    out: list[Finding] = []
    for file in inputs.reviewed_files():
        if is_test_path(file.path) or file.language not in {"python", "typescript", "javascript"}:
            continue
        script = _is_script(file.path)
        for line in file.added:
            text = line.content
            if COMMENT.match(text):
                continue
            if BREAKPOINTS.search(text):
                out.append(
                    finding(
                        "debug_statements",
                        file,
                        line.new_no,
                        severity="high",
                        category="hygiene",
                        title="Breakpoint left in the code",
                        explanation="A debugger stop in committed code halts or dumps state.",
                        suggestion="Remove it before merging.",
                    )
                )
            elif not script and (
                (file.language != "python" and CONSOLE.search(text))
                or (file.language == "python" and PRINT.match(text))
            ):
                out.append(
                    finding(
                        "debug_statements",
                        file,
                        line.new_no,
                        severity="low",
                        category="hygiene",
                        title="Debug output left in library code",
                        explanation=(
                            "Printing from library code bypasses the logger: no level, no "
                            "structure, and it shows up in every caller's output."
                        ),
                        suggestion="Use the logger, or remove it.",
                    )
                )
    return out


CHECK = Check("debug_statements", "Breakpoints and stray console/print output", run)

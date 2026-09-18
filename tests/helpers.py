"""Build small unified diffs in tests without hand-counting hunk headers."""

from __future__ import annotations

import difflib

from second_opinion.checks import run_checks
from second_opinion.diff import Diff, filter_diff, parse_diff
from second_opinion.findings import Finding


def make_diff(files: dict[str, str | tuple[str, str]], *, status: str = "added") -> str:
    """Each value is the new content (an added file), or `(old, new)` for a modified file whose
    entire body is shown as one hunk with the old lines removed and the new lines added."""
    parts: list[str] = []
    for path, spec in files.items():
        if isinstance(spec, tuple):
            old, new = spec
            body = "".join(
                difflib.unified_diff(
                    old.splitlines(keepends=True),
                    new.splitlines(keepends=True),
                    fromfile=f"a/{path}",
                    tofile=f"b/{path}",
                )
            )
            parts.append(f"diff --git a/{path} b/{path}\nindex 1111111..2222222 100644\n{body}")
        else:
            new_lines = spec.splitlines()
            body = "".join(f"+{line}\n" for line in new_lines)
            parts.append(
                f"diff --git a/{path} b/{path}\nnew file mode 100644\n"
                f"index 0000000..1111111\n--- /dev/null\n+++ b/{path}\n"
                f"@@ -0,0 +1,{len(new_lines)} @@\n{body}"
            )
    return "".join(parts)


def checks_for(
    files: dict[str, str | tuple[str, str]], *, only: str | None = None
) -> list[Finding]:
    diff: Diff = parse_diff(make_diff(files))
    return run_checks(filter_diff(diff), diff, only={only} if only else None)

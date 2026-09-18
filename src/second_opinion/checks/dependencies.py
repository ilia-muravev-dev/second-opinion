"""Manifests and lockfiles: a lockfile that changed without its manifest (or the reverse), and
dependencies added — each one is a review of its own (license, maintenance, size)."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from second_opinion.checks.base import Check, CheckInput, finding
from second_opinion.diff import Diff, FileDiff
from second_opinion.findings import Finding

LOCK_TO_MANIFEST: dict[str, tuple[str, ...]] = {
    "pnpm-lock.yaml": ("package.json",),
    "package-lock.json": ("package.json",),
    "yarn.lock": ("package.json",),
    "uv.lock": ("pyproject.toml",),
    "poetry.lock": ("pyproject.toml",),
    "Cargo.lock": ("Cargo.toml",),
    "go.sum": ("go.mod",),
}
JSON_DEP = re.compile(
    r'^\s*"(@?[A-Za-z0-9_./-]+)"\s*:\s*"([~^>=<]?\d[^"]*|workspace:[^"]*|latest)"\s*,?\s*$'
)
PY_DEP = re.compile(r'^\s*"([A-Za-z0-9_.\[\]-]+)\s*(?:[<>=!~;].*)?"\s*,?\s*$')
PY_SECTION = re.compile(
    r"^\s*(?:dependencies\s*=\s*\[|dev\s*=\s*\[|\[project\.optional-dependencies\])"
)


def _by_name(diff: Diff) -> dict[str, list[FileDiff]]:
    out: dict[str, list[FileDiff]] = {}
    for file in diff.files:
        out.setdefault(PurePosixPath(file.path).name, []).append(file)
    return out


def _same_dir(a: str, b: str) -> bool:
    return PurePosixPath(a).parent == PurePosixPath(b).parent


def run(inputs: CheckInput) -> list[Finding]:
    out: list[Finding] = []
    names = _by_name(inputs.full)
    # lockfile without manifest, manifest without lockfile
    for lock_name, manifests in LOCK_TO_MANIFEST.items():
        for lock in names.get(lock_name, []):
            partners = [m for name in manifests for m in names.get(name, [])]
            if not any(_same_dir(lock.path, m.path) for m in partners):
                out.append(
                    finding(
                        "dependencies",
                        lock,
                        None,
                        severity="medium",
                        category="dependencies",
                        title=f"{lock_name} changed without its manifest",
                        explanation=(
                            "A lockfile that moves on its own means the resolved versions changed "
                            "without a declared reason — usually an unintended update."
                        ),
                        suggestion=(
                            "Re-run the install from the manifest, or mention the intended update."
                        ),
                    )
                )
    for manifest_name in {m for ms in LOCK_TO_MANIFEST.values() for m in ms}:
        for manifest in names.get(manifest_name, []):
            if manifest.status != "modified":
                continue
            added = _added_dependencies(manifest)
            if not added:
                continue
            locks = [
                lock
                for lock_name, manifests in LOCK_TO_MANIFEST.items()
                if manifest_name in manifests
                for lock in names.get(lock_name, [])
                if _same_dir(lock.path, manifest.path)
            ]
            if not locks:
                first_line = added[0][1]
                out.append(
                    finding(
                        "dependencies",
                        manifest,
                        first_line,
                        severity="medium",
                        category="dependencies",
                        title="Dependencies added without a lockfile change",
                        explanation=(
                            "The manifest gained dependencies but no lockfile changed with it."
                        ),
                        suggestion="Run the install and commit the lockfile.",
                    )
                )
            for name, line in added:
                out.append(
                    finding(
                        "dependencies",
                        manifest,
                        line,
                        severity="low",
                        category="dependencies",
                        title=f"New dependency: {name}",
                        explanation="A new dependency is a maintenance and licence commitment.",
                        suggestion="Say why it is needed and check its licence and activity.",
                    )
                )
    return out


def _added_dependencies(manifest: FileDiff) -> list[tuple[str, int | None]]:
    added: list[tuple[str, int | None]] = []
    name = PurePosixPath(manifest.path).name
    for hunk in manifest.hunks:
        in_section = False
        for line in hunk.lines:
            text = line.content
            if name == "package.json":
                if re.match(r'^\s*"(?:dev|peer|optional)?[dD]ependencies"\s*:\s*\{', text):
                    in_section = True
                    continue
                if in_section and re.match(r"^\s*\},?\s*$", text):
                    in_section = False
                    continue
                match = JSON_DEP.match(text)
                if in_section and line.kind == "added" and match:
                    added.append((match.group(1), line.new_no))
            elif name == "pyproject.toml":
                if PY_SECTION.match(text):
                    in_section = True
                    continue
                if in_section and re.match(r"^\s*\]\s*$", text):
                    in_section = False
                    continue
                match = PY_DEP.match(text)
                if in_section and line.kind == "added" and match:
                    added.append((match.group(1), line.new_no))
    return added


CHECK = Check("dependencies", "Lockfile/manifest consistency and added dependencies", run)

"""Credentials in a diff: exact token shapes, and the generic `password = "…"` assignment when
the value does not look like a placeholder."""

from __future__ import annotations

import re

from second_opinion.checks.base import Check, CheckInput, finding, is_test_path
from second_opinion.findings import Finding

TOKEN_SHAPES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("Stripe live key", re.compile(r"\b[sr]k_live_[A-Za-z0-9]{16,}\b")),
    ("OpenAI/Anthropic-style key", re.compile(r"\bsk-(?:ant-|or-|proj-)?[A-Za-z0-9_-]{24,}\b")),
    (
        "private key block",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
    ),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
)

ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token|private[_-]?key)"
    r"['\"]?\s*[:=]\s*['\"]([^'\"]{8,})['\"]"
)
# A value that says what it is — a test, a sample, a dev default — is not a leaked credential.
PLACEHOLDER = re.compile(
    r"(?i)(\$\{|\{\{|<[^>]+>|xxx+|change[_-]?me|example|placeholder|your[_-]|dummy|redacted|"
    r"\*{3,}|process\.env|os\.environ|getenv|env\(|test|dev\b|_dev|fake|sample|mock|local|"
    r"secret|password|hunter)"
)


def _looks_real(value: str) -> bool:
    if PLACEHOLDER.search(value):
        return False
    classes = sum(
        1 for rx in (r"[a-z]", r"[A-Z]", r"[0-9]", r"[^A-Za-z0-9]") if re.search(rx, value)
    )
    return len(set(value)) > 6 and (classes >= 3 or len(value) >= 20)


def run(inputs: CheckInput) -> list[Finding]:
    out: list[Finding] = []
    for file in inputs.full.files:
        if file.is_binary:
            continue
        in_tests = is_test_path(file.path)
        for line in file.added:
            hit = next((name for name, rx in TOKEN_SHAPES if rx.search(line.content)), None)
            if hit is None:
                match = ASSIGNMENT.search(line.content)
                if match and _looks_real(match.group(2)):
                    hit = f"{match.group(1)} assigned a literal"
            if hit is None:
                continue
            out.append(
                finding(
                    "secrets",
                    file,
                    line.new_no,
                    severity="medium" if in_tests else "high",
                    category="security",
                    title=f"Possible credential in the diff: {hit}",
                    explanation=(
                        "A value shaped like a credential is committed on this line. Once it is "
                        "in history it has to be rotated, even if the commit is amended."
                    ),
                    suggestion=(
                        "Move it to an environment variable or a secret store and rotate it."
                    ),
                )
            )
    return out


CHECK = Check("secrets", "Credentials and private keys committed in the diff", run)

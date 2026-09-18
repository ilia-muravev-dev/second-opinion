from pathlib import Path

from second_opinion.checks import run_checks
from second_opinion.diff import filter_diff, parse_diff
from second_opinion.findings import Finding

from .helpers import checks_for

CORPUS = Path(__file__).resolve().parents[1] / "evals" / "corpus"


def titles(findings: list[Finding]) -> list[str]:
    return [f.title for f in findings]


# --- secrets -------------------------------------------------------------------------------


def test_secrets_fire_on_token_shapes_and_literal_assignments() -> None:
    found = checks_for(
        {
            "src/config.py": (
                'AWS = "AKIAIOSFODNN7EXAMPLE"\n'
                'token = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"\n'
                'password = "Tr0ub4dor&3-horse-battery"\n'
                "-----BEGIN RSA PRIVATE KEY-----\n"
            )
        },
        only="secrets",
    )
    assert len(found) == 4
    assert all(f.severity == "high" and f.category == "security" for f in found)
    assert [f.line for f in found] == [1, 2, 3, 4]


def test_secrets_ignore_placeholders_and_soften_in_tests() -> None:
    quiet = checks_for(
        {
            "src/config.py": (
                'password = os.environ["PASSWORD"]\n'
                'api_key = "${API_KEY}"\n'
                'secret = "changeme"\n'
                'token = "<your-token>"\n'
                'STRIPE_WEBHOOK_SECRET = "whsec_slotlock_dev"\n'
                'SECRET = "whsec_test_secret"\n'
                'password = "hunter2hunter2"\n'
            )
        },
        only="secrets",
    )
    assert quiet == []
    in_tests = checks_for(
        {"tests/test_auth.py": 'password = "Tr0ub4dor&3-horse-battery"\n'}, only="secrets"
    )
    assert [f.severity for f in in_tests] == ["medium"]


# --- debug statements ------------------------------------------------------------------------


def test_debug_statements_flag_breakpoints_and_console_output() -> None:
    found = checks_for(
        {
            "src/service.ts": "const x = 1;\nconsole.log(x);\ndebugger;\n",
            "src/lib.py": "def f():\n    print('here')\n    breakpoint()\n",
        },
        only="debug_statements",
    )
    assert sorted((f.file, f.line, f.severity) for f in found) == [
        ("src/lib.py", 2, "low"),
        ("src/lib.py", 3, "high"),
        ("src/service.ts", 2, "low"),
        ("src/service.ts", 3, "high"),
    ]


def test_debug_statements_allow_clis_scripts_tests_and_comments() -> None:
    quiet = checks_for(
        {
            "src/cli.py": "print('usage')\n",
            "scripts/demo.ts": "console.log('demo');\n",
            "tests/test_x.py": "print('debugging a test')\n",
            "src/other.ts": "// console.log is documented here\n",
        },
        only="debug_statements",
    )
    assert quiet == []


# --- skipped tests ---------------------------------------------------------------------------


def test_skipped_and_focused_tests() -> None:
    found = checks_for(
        {
            "test/a.test.ts": "it.only('x', () => {});\ndescribe.skip('y', () => {});\n",
            "tests/test_b.py": "@pytest.mark.skip(reason='later')\ndef test_b(): ...\n",
        },
        only="skipped_tests",
    )
    assert sorted((f.file, f.line, f.severity) for f in found) == [
        ("test/a.test.ts", 1, "high"),
        ("test/a.test.ts", 2, "medium"),
        ("tests/test_b.py", 1, "medium"),
    ]
    assert checks_for({"test/a.test.ts": "it('x', () => {});\n"}, only="skipped_tests") == []


# --- markers ---------------------------------------------------------------------------------


def test_markers_ignore_generated_files_except_conflicts() -> None:
    found = checks_for(
        {"src/generated/x.ts": "// TODO: generated\n// @ts-ignore\n<<<<<<< HEAD\n"}, only="markers"
    )
    assert titles(found) == ["Merge conflict marker committed"]


def test_markers() -> None:
    found = checks_for(
        {
            "src/a.ts": (
                "// TODO: later\n<<<<<<< HEAD\nconst a = 1; // eslint-disable-line\n// @ts-ignore\n"
            )
        },
        only="markers",
    )
    assert [(f.line, f.severity) for f in found] == [
        (2, "high"),
        (4, "medium"),
        (1, "low"),
        (3, "low"),
    ]
    assert checks_for({"src/a.ts": "const a = 1;\n"}, only="markers") == []


# --- dependencies ----------------------------------------------------------------------------


def test_lockfile_without_manifest_and_new_dependencies() -> None:
    lock_only = checks_for({"pnpm-lock.yaml": ("a: 1\n", "a: 2\n")}, only="dependencies")
    assert titles(lock_only) == ["pnpm-lock.yaml changed without its manifest"]
    assert lock_only[0].line is None

    manifest_only = checks_for(
        {
            "package.json": (
                '{\n  "dependencies": {\n    "left-pad": "^1.0.0"\n  }\n}\n',
                '{\n  "dependencies": {\n    "left-pad": "^1.0.0",\n'
                '    "is-odd": "^3.0.1"\n  }\n}\n',
            )
        },
        only="dependencies",
    )
    assert titles(manifest_only) == [
        "Dependencies added without a lockfile change",
        "New dependency: left-pad",
        "New dependency: is-odd",
    ]

    both = checks_for(
        {
            "pyproject.toml": (
                'dependencies = [\n  "httpx>=0.28",\n]\n',
                'dependencies = [\n  "httpx>=0.28",\n  "orjson>=3",\n]\n',
            ),
            "uv.lock": ("a: 1\n", "a: 2\n"),
        },
        only="dependencies",
    )
    assert titles(both) == ["New dependency: orjson"]


# --- files -----------------------------------------------------------------------------------


def test_edited_migration_and_env_file() -> None:
    found = checks_for(
        {
            "prisma/migrations/20260918_init/migration.sql": (
                "CREATE TABLE a;\n",
                "CREATE TABLE b;\n",
            ),
            ".env": "SECRET=1\n",
            ".env.example": "SECRET=\n",
        },
        only="files",
    )
    assert sorted(titles(found)) == [".env committed", "An existing migration was edited"]
    new_migration = checks_for(
        {"prisma/migrations/20260919_more/migration.sql": "CREATE TABLE c;\n"}, only="files"
    )
    assert new_migration == []


def test_untested_source_and_large_pr() -> None:
    body = "".join(f"const v{i} = {i};\n" for i in range(50))
    untested = checks_for({"src/big.ts": body}, only="files")
    assert titles(untested) == ["Source changed, no test changed"]
    tested = checks_for(
        {"src/big.ts": body, "test/big.test.ts": "it('x', () => {});\n"}, only="files"
    )
    assert tested == []
    big = "".join(f"line {i}\n" for i in range(800))
    large = checks_for({"docs/a.md": big, "docs/b.md": big}, only="files")
    assert titles(large) == ["Large pull request (1600 changed lines after filters)"]


# --- the corpus is mostly quiet --------------------------------------------------------------


def test_corpus_checks_are_specific() -> None:
    """The real pull requests should not drown in deterministic findings: a sanity bound."""
    noisy: dict[str, int] = {}
    for path in sorted(CORPUS.glob("*/*.diff")):
        diff = parse_diff(path.read_text())
        found = run_checks(filter_diff(diff), diff)
        high = [f for f in found if f.severity == "high"]
        noisy[f"{path.parent.name}/{path.stem}"] = len(high)
    assert sum(noisy.values()) <= 4, noisy

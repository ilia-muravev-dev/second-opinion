# second-opinion task runner — `just` lists the recipes.

default:
    @just --list

# Install everything (uv)
install:
    uv sync --frozen

# Lint, format check, types, tests
check:
    uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest

# Fix what ruff can fix and format
fix:
    uv run ruff check --fix . && uv run ruff format .

# Review a unified diff from a file with the configured provider (markdown on stdout)
review diff:
    uv run second-opinion review --diff {{diff}}

# Regenerate the eval cases from the corpus (deterministic); --check in CI
eval-build:
    uv run second-opinion eval build

# Run the eval set with the configured provider, recording responses (resumable across the daily cap)
eval-run prompt="v1":
    uv run second-opinion eval run --prompt {{prompt}} --cassette record

# Re-score a run from its recorded responses (no requests) and rewrite its report
eval-replay prompt="v1":
    uv run second-opinion eval run --prompt {{prompt}} --cassette replay --force --yes

# Compare runs: just eval-compare "a--v1 a--v2"
eval-compare slugs:
    uv run second-opinion eval compare {{slugs}}

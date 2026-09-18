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

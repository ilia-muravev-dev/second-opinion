# second-opinion — notes for coding agents

Python 3.12, uv, Typer CLI, pydantic v2, httpx; Anthropic SDK and an OpenAI-compatible client
behind one provider protocol; shipped as a composite GitHub Action.

## Commands
- `just check` — ruff, format check, mypy strict, pytest (unit tests use the fake provider; nothing
  in the suite talks to a network)
- `just fix` — ruff fixes + format
- `uv run second-opinion --help` — the CLI: `review`, `checks`, `eval build|run|report|compare`,
  `gate write|check`
- `just eval-build` (deterministic; CI runs `eval build --check`), `just eval-run v3` (records
  cassettes, resumes across the free tier's daily cap), `just eval-compare "<slug> <slug>"`
- The repository reviews its own PRs (`.github/workflows/review.yml`) with the action from the PR
  branch and the `OPENROUTER_API_KEY` secret; each PR costs a couple of the day's free requests

## Rules of the codebase
- Every review finding is anchored to a file and a line in the diff, or it goes to the summary
  only. Never post a comment on a line that is not in the pull request's hunks.
- Models are called only through `second_opinion.llm.provider`; the fake and cassette providers
  are drop-in replacements and are what tests and the CI eval gate use.
- Numbers in the README come only from reports under `docs/evals/` written by the eval runner.
  A prompt change must be re-measured and its report committed in the same pull request.
- The eval set is generated (`eval build`) from committed corpus diffs by seeded mutation
  operators; do not hand-edit generated cases. Add an operator instead, and regenerate the index.
- Prompt versions are a registry (`review/registry.py`); a new version gets a new name and its
  own measured run — never edit a prompt a report was written against.
- A model outage never fails a pull request's check; only `--fail-on` does.
- Warnings are errors in pytest; mypy is strict; keep functions typed.

## Review checklist for PRs
- Does a test prove the behaviour (a check fires on the positive fixture and stays silent on the
  negative one; a finding anchors to the right line), or only that code ran?
- Any change to what is posted to GitHub: idempotent on re-run (summary updated in place, no
  duplicate inline comments)?

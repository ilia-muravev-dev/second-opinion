# second-opinion

**A pull-request reviewer that measures itself.**

[![CI](https://github.com/ilia-muravev-dev/second-opinion/actions/workflows/ci.yml/badge.svg)](https://github.com/ilia-muravev-dev/second-opinion/actions/workflows/ci.yml)

Three layers, each with a job the others do badly, and a number for each:

1. **Deterministic checks** run first, always, for free: credentials in the diff, breakpoints and
   stray `console.log`/`print`, skipped or focused tests, TODO/suppression/conflict markers,
   lockfiles out of step with their manifest, new dependencies, an applied migration edited, an
   `.env` committed, a pull request too large to review well, source changed with no test touched.
2. **A model review** with a strict output schema (`file`, `line`, `severity`, `category`,
   `title`, `explanation`, `suggestion`, `confidence`) over the filtered diff — lockfiles,
   generated code, vendored trees and binaries are not sent — rendered with new-side line numbers
   so every finding cites the line a comment will be anchored to.
3. **The second opinion**: every model finding goes back with the hunk it is about and the
   question "is this real?". Rejected findings are dropped (and listed in the summary with the
   reason); the rest are posted with their verdict.

The whole thing is scored against **real pull requests with planted defects** — the merged pull
requests of three repositories, each replayed untouched (the false-positive set) and with one
injected defect at a time (off-by-one, inverted condition, dropped `await`/`return`/`throw`/lock,
swapped status literal, narrowed filter, committed credential, switched-off test), 94 cases over
21 operators. Recall, precision and the false-positive rate per prompt version and model, from
reports the runner writes. See [ADR 0002](docs/adr/0002-evals-from-real-pull-requests-with-planted-defects.md)
for what those numbers do and do not measure.

## Results

RESULTS_PLACEHOLDER

## What it posts

One review with inline comments for anchored findings, tagged so a re-run does not repeat them,
and one summary comment — findings table, what was skipped and why, the model's summary of the
change, tokens and cost — edited in place on later pushes. Findings the diff cannot anchor go to
the summary. If GitHub refuses the inline comments, everything goes to the summary; if the model is
rate limited or misconfigured, the deterministic findings still post with a note. The check fails
only when you ask it to (`fail-on: high`). [ADR 0003](docs/adr/0003-anchoring-and-re-runs.md).

The repository reviews its own pull requests with the action from the pull request's branch —
open any merged PR to see what it said, including the two real defects it found in
[its own posting code](https://github.com/ilia-muravev-dev/second-opinion/pull/4).

## Use it

```yaml
# .github/workflows/review.yml
name: Second opinion
on: pull_request
permissions:
  contents: read
  pull-requests: write
jobs:
  review:
    if: github.event.pull_request.head.repo.full_name == github.repository  # forks get no secrets
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: ilia-muravev-dev/second-opinion@main
        with:
          provider: anthropic
          model: claude-haiku-4-5-20251001
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
          prompt: v3
          # or any OpenAI-compatible endpoint:
          # provider: openai
          # model: deepseek/deepseek-v4-flash-0731:free
          # openai-api-key: ${{ secrets.OPENROUTER_API_KEY }}
          # openai-base-url: https://openrouter.ai/api/v1
```

Inputs: `provider`, `model`, the keys, `prompt` (`v1` plain · `v2` rubric · `v3` rubric + second
opinion), `min-confidence`, `max-findings`, `post` (`review` | `summary` | `none`), `fail-on`
(`none` | `high` | `medium` | `low`). Outputs: `findings`, `high`, `requests`, `cost_usd`.

Locally:

```bash
uv sync
uv run second-opinion checks --diff some.diff                      # the deterministic layer only
uv run second-opinion review --diff some.diff --provider openai     # markdown on stdout
uv run second-opinion review --pr 12 --repo owner/name --post none  # needs GITHUB_TOKEN
```

Configuration is environment variables prefixed `SO_` (see `.env.example`); reasoning is off by
default (`SO_EFFORT=none`) because a review is a reading task and free reasoning models think for
minutes.

## Measure it

```bash
just eval-build              # 94 cases from evals/corpus + evals/operators.yaml (deterministic; CI checks the index)
just eval-run v3             # reviews every case, records responses, resumes across a daily request cap
just eval-compare "deepseek-deepseek-v4-flash-0731-free--v1 deepseek-deepseek-v4-flash-0731-free--v3"
uv run second-opinion gate check   # CI: re-score the baseline run from cassettes, fail on a drop
```

A finding hits a planted defect when it names the file and lands within three lines; each
defect counts once; a deterministic check's hit counts. Findings on mutated pull requests that hit
nothing are reported as *unlabelled* — the original pull requests may carry real issues — never
silently counted as wrong. Clean pull requests give the false-positive rate directly.

## Design notes

- [ADR 0001 — deterministic first, then a model, then a second opinion — and a number for each](docs/adr/0001-deterministic-first-then-a-model-then-a-second-opinion.md)
- [ADR 0002 — the eval set is real pull requests with planted defects, not human labels](docs/adr/0002-evals-from-real-pull-requests-with-planted-defects.md)
- [ADR 0003 — findings anchor to diff lines or stay in the summary; re-runs edit, never repeat](docs/adr/0003-anchoring-and-re-runs.md)

Things worth a reviewer's attention:

- The first real run flagged `actions/checkout@v7` as "non-existent": a model's knowledge has a
  cutoff and the code is newer than it. Prompt `v2` forbids that class of finding; the verifier
  is told to reject it.
- Free reasoning models on OpenRouter think until `max_tokens` and answer with nothing. The
  provider detects the empty answer and asks once more with reasoning off.
- GitHub's push protection refused the eval set's planted Stripe key, which is the check working
  as intended; the planted credential is now a made-up shape that the tool's own `secrets` check
  (and, one hopes, the model) still flags.
- The reviewer reviewed the pull request that taught it to post reviews and found two defects in
  it — the fallback only covered 422 and a comment range could cross a hunk. Both fixed.

## Layout

```
src/second_opinion/
  diff/        parse · filters · chunk (numbered rendering, budgets) · serialize
  checks/      one module per deterministic check, a registry
  llm/         provider protocol · anthropic · openai_compat · fake · cassette · pricing
  review/      prompts/{v1,v2,v3-verify}.md · schema · reviewer · verifier · merge · registry
  github/      client (pull request, diff, review, summary upsert) · post (anchors, fingerprints, fallbacks)
  evals/       corpus · mutate (operators) · dataset · match · metrics · runner (resumable) · report
  gate/        baseline write / check on replayed cassettes
  pipeline.py  one review end to end, used by the CLI, the action and the eval runner
evals/         corpus/ (33 real PR diffs) · operators.yaml · cases.index.json · runs/ · cassettes/
docs/          adr/ · evals/ (the runner's reports)
action.yml     the composite action
```

## Stack

Python 3.12 · uv · Typer · pydantic v2 · httpx · Anthropic SDK · OpenAI SDK (OpenRouter, Ollama,
any compatible endpoint) · ruff · mypy strict · pytest + respx · GitHub composite action.

## What is missing on purpose

A GitHub App (the action is enough and needs no hosting), incremental review of only the new
commits (the fingerprints make re-runs cheap enough), and any claim about defects that need code
outside the diff.

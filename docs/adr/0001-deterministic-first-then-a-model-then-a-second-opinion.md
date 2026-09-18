# ADR 0001: Deterministic checks first, then a model, then a second opinion — and a number for each

Status: accepted · 2026-09-18

## Context

An LLM review comment costs the author attention whether it is right or wrong, and the wrong ones
cost more: after a few, every comment is skimmed. A reviewer earns trust with precision, and it
can only claim precision if it is measured. Most AI review tools publish neither the measurement
nor the method.

## Decision

Three layers, each with a job the others do badly:

1. **Deterministic checks** run first and always. A leaked key, a `console.log`, a skipped test, a
   lockfile without its manifest: regexes and file lists find these with certainty and for free.
   Their findings are also handed to the model so it does not spend its budget repeating them.
2. **A model review** with a structured output schema (`file`, `line`, `severity`, `category`,
   `title`, `explanation`, `suggestion`, `confidence`) over the filtered diff. The prompt is
   versioned and lives in the repository; the schema is the contract.
3. **A second opinion**: every model finding is sent back with its hunk and the question "is this
   real, given the code?". Only confirmed or plausible findings are posted; rejections stay in the
   log with their reason. The name of the project is this step.

And a measurement: an eval set of real pull requests with injected defects (ADR 0002), scored for
recall (did it find the planted bug), precision (how much of what it said hit a planted bug) and
false positives per clean pull request, per prompt version and model, with the tokens spent.
The README shows the table the runner writes; it is never edited by hand.

## Consequences

- The second pass roughly doubles the model tokens per finding. The eval shows whether it pays.
- Findings must anchor to a line inside the diff or they go to the summary: a comment on a line
  GitHub cannot show is worse than no comment.
- The eval set measures planted defects. Real pull requests may carry real, unlabelled issues;
  findings that hit no label are reported as "unlabelled", never silently counted as wrong.

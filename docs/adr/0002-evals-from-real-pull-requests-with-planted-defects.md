# ADR 0002: The eval set is real pull requests with planted defects, not human labels

Status: accepted · 2026-09-19

## Context

To say "this reviewer finds X% of defects with Y% precision" you need pull requests whose
defects are known. Human review comments on public pull requests are the obvious labels and the
wrong ones: they are incomplete (reviewers miss things), inconsistent (what one blocks another
waves through), entangled with taste, and they say nothing about the many diffs that were fine.
Hand-written toy pull requests have exact labels but none of the noise that makes review hard.

## Decision

Take the merged pull requests of three real repositories (the author's own, so the code is known
and the licence is clear), and generate the set:

- every pull request, untouched, is a **clean case** — it measures false positives;
- up to three copies of it carry **one planted defect** each: a mutation operator from a small,
  declared catalogue (`evals/operators.yaml`) applied to one added line — a loosened comparison,
  an inverted condition, a dropped `await`, `return`, `throw` or lock, a swapped status literal,
  a narrowed filter, a committed credential, a switched-off test. The label is that line.

The generator is seeded and deterministic and prefers operators the set has seen least, so the
catalogue is covered evenly rather than by how often each pattern occurs. The committed index
pins ids, labels and diff digests; CI rebuilds and compares.

Scoring: a finding hits a label when it names the file and lands within three lines; each label
counts once; a deterministic check's hit counts as much as the model's. Recall is labels found.
Precision is the share of the model's findings on mutated cases that hit the planted defect —
and because the original pull requests may carry real, unlabelled issues, the findings that hit
nothing are reported as *unlabelled*, never silently counted as wrong. Clean cases give the
false-positive rate directly.

## Consequences

- The numbers are exact and reproducible, and they measure one thing: does the reviewer notice a
  planted, realistic, one-line defect in a realistic diff. They do not measure whether it would
  find a design flaw, or a bug that needs code outside the diff.
- The catalogue is small and public, so a prompt could be tuned to it. The review prompt
  describes classes of defect a reviewer looks for — that is what a rubric is — but names no
  operator; the unlabelled-findings column and the clean-case rate are the check on over-fitting.
- Each mutated case is a whole pull request, so a run costs as many requests as there are cases
  (more for large diffs). Under a free provider's daily cap the runner resumes across days.

# ADR 0003: Findings anchor to diff lines or stay in the summary; re-runs edit, never repeat

Status: accepted · 2026-09-19

## Context

GitHub shows a review comment only on a line that is part of the pull request's diff and
rejects the whole review (422) when any comment points elsewhere. A model that cites a line it
did not see, or a line that moved, would either lose the review or comment in the wrong place.
And a reviewer that runs on every push must not say the same thing five times.

## Decision

- The diff is rendered with new-side line numbers in front of every line, and the model is told
  to cite them. A finding whose file is not in the diff is dropped; a finding whose line the diff
  does not show keeps its text but loses its anchor and goes to the summary. Nothing is ever
  posted on a line the diff does not contain.
- Inline comments carry a fingerprint (file + normalised title, no line) in an HTML comment.
  On a re-run the fingerprints already on the pull request are skipped; the summary comment is
  found by its marker and edited in place. If GitHub still refuses the inline anchors, the whole
  review goes to the summary with a note — a lost review is worse than an unanchored one.
- A rate-limited or misconfigured model never fails the check: the deterministic findings still
  post, with a note that the model did not run. `fail-on` is the only way the action fails a
  pull request, and it is off by default.

## Consequences

- A finding that moved by a line on a later push is not re-posted; a genuinely new finding
  about the same file with the same title is not either. That is the intended trade.
- The summary is the durable record; inline comments are a convenience on top of it.

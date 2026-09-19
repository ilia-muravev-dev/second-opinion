# Eval run `nex-agi-nex-n2.5-pro-free--v1`

Model `nex-agi/nex-n2.5-pro:free` via openrouter, prompt `v1`, 58 cases (37 with one planted defect each, 21 clean), written 2026-09-19 10:12 UTC by `second-opinion eval report`.

**recall 73.0% (27/37, 95% CI 57.0% to 84.6%), precision 19.7% (23/117), 1.86 model findings per clean PR**

| Metric | Value |
| --- | --- |
| Recall (planted defects found) | 73.0% — 27/37, 95% CI 57.0% to 84.6% |
| … of which found by a deterministic check | 4 |
| Precision (model findings on mutated PRs that hit the defect) | 19.7% — 23/117 |
| Unlabelled model findings per mutated PR | 2.54 |
| Model findings per clean PR (false positives, by construction) | 1.86 — 39 over 21 |
| Category agreed, of found | 21/27 |
| Requests | 70 (1.2 per case) |
| Tokens in / out | 982,286 / 31,944 |
| Cost | $0.0000 |
| Cases with a model error | 0 |

Unlabelled findings on mutated PRs are not counted as wrong: the original pull requests may carry real issues. A sample should be read by hand before drawing conclusions from precision alone.

## By operator

| Operator | Found | Of |
| --- | ---: | ---: |
| `and_to_or` | 1 | 1 |
| `and_to_or_py` | 2 | 3 |
| `dropped_await` | 2 | 2 |
| `dropped_not` | 0 | 1 |
| `dropped_not_py` | 3 | 3 |
| `dropped_raise` | 1 | 3 |
| `dropped_return` | 2 | 2 |
| `dropped_return_py` | 3 | 3 |
| `dropped_throw` | 1 | 1 |
| `hardcoded_secret` | 3 | 3 |
| `inverted_equality` | 0 | 2 |
| `inverted_equality_py` | 4 | 4 |
| `min_max` | 1 | 2 |
| `min_max_py` | 2 | 3 |
| `off_by_one_gte` | 0 | 1 |
| `off_by_one_lt` | 0 | 1 |
| `plus_minus_one` | 1 | 1 |
| `skipped_test` | 1 | 1 |

## By category

| Category | Found | Of |
| --- | ---: | ---: |
| concurrency | 2 | 2 |
| correctness | 19 | 27 |
| error_handling | 2 | 4 |
| security | 3 | 3 |
| testing | 1 | 1 |

## Missed

| Case | Operator | Where |
| --- | --- | --- |
| `fieldwise-pr1-m2` | `off_by_one_lt` | `backend/scripts/make_fixtures.py:25` |
| `fieldwise-pr10-m1` | `inverted_equality` | `web/src/app/documents/[id]/review.tsx:88` |
| `fieldwise-pr10-m3` | `min_max` | `web/src/components/accuracy-bar.tsx:11` |
| `fieldwise-pr14-m1` | `dropped_not` | `web/src/app/api/[...path]/route.ts:24` |
| `fieldwise-pr2-m3` | `min_max_py` | `backend/src/fieldwise/documents/ocr.py:110` |
| `fieldwise-pr3-m1` | `dropped_raise` | `backend/src/fieldwise/extraction/pipeline.py:48` |
| `fieldwise-pr3-m2` | `off_by_one_gte` | `backend/src/fieldwise/extraction/openai_compat.py:122` |
| `fieldwise-pr7-m2` | `dropped_raise` | `backend/src/fieldwise/api/routers/runs.py:15` |
| `fieldwise-pr7-m3` | `and_to_or_py` | `backend/src/fieldwise/worker/app.py:21` |
| `single-flight-auth-pr1-m3` | `inverted_equality` | `src/storage.ts:4` |

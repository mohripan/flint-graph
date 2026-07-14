# Evaluation QA Guide

Use this guide to validate Milestone 09 without paid model calls.

## Offline Quality Gate

Run:

```powershell
uv run atlas-eval run --dataset evals/datasets/acme-smoke --evaluations evals/reports/acme-smoke/deterministic-recorded.jsonl --experiment evals/experiments/acme-smoke.yaml --baseline evals/reports/acme-smoke/baselines.json --config-name deterministic
```

Expected result:

- exit code `0`;
- output starts with `deterministic @ acme-smoke v1`;
- threshold and baseline failures are absent.

## Full Local Check

Run:

```powershell
uv run pytest
uv run ruff check .
uv run mypy
uv run alembic upgrade head --sql
docker compose config
```

`make check` runs the same lint/typecheck/test sequence plus the offline eval gate on Unix-like
shells.

## CI Expectations

- `.github/workflows/ci.yml` runs the offline deterministic eval gate on PRs and pushes.
- `.github/workflows/live-eval.yml` is scheduled/manual and requires live secrets plus a live
  captured recording file. It is not part of PR CI.

## Interpreting Failures

- `missing metric`: the recorded evaluation no longer produces a metric stored in the baseline
  or experiment thresholds.
- `min` or `max`: the current aggregate violates the fixed threshold in
  `evals/experiments/acme-smoke.yaml`.
- `regression`: the current aggregate moved beyond the accepted value in
  `evals/reports/acme-smoke/baselines.json`.

Do not update baselines to make a failure disappear. First decide whether the behavior change is
intended and whether the labels or recorded evaluations need to change.

# Evaluation Developer Runbook

The evaluation platform is file-based and offline by default.

## Layout

```text
evals/
  datasets/acme-smoke/
    corpus/
    dataset.yaml
    queries.jsonl
  experiments/acme-smoke.yaml
  reports/acme-smoke/
    deterministic-recorded.jsonl
    baselines.json
```

`queries.jsonl` contains stable labels. `deterministic-recorded.jsonl` contains one recorded
`QueryEvaluation` per query. Reports and baselines are reviewable repo files.

## Run The Offline Gate

```powershell
uv run atlas-eval run `
  --dataset evals/datasets/acme-smoke `
  --evaluations evals/reports/acme-smoke/deterministic-recorded.jsonl `
  --experiment evals/experiments/acme-smoke.yaml `
  --baseline evals/reports/acme-smoke/baselines.json `
  --config-name deterministic
```

The same command is available as:

```bash
make eval-gate
```

## Update A Baseline

Only update a baseline when the metric movement is intentional.

```powershell
uv run atlas-eval run `
  --dataset evals/datasets/acme-smoke `
  --evaluations evals/reports/acme-smoke/deterministic-recorded.jsonl `
  --report evals/reports/acme-smoke/deterministic-latest.json `
  --config-name deterministic

uv run atlas-eval baseline update `
  --report evals/reports/acme-smoke/deterministic-latest.json `
  --baseline evals/reports/acme-smoke/baselines.json
```

Review the baseline diff. Baselines never move automatically.

## Compare Configurations

```powershell
uv run atlas-eval compare `
  --dataset evals/datasets/acme-smoke `
  --evaluations deterministic=evals/reports/acme-smoke/deterministic-recorded.jsonl `
  --evaluations candidate=evals/reports/acme-smoke/deterministic-recorded.jsonl `
  --output evals/reports/acme-smoke/comparison.md `
  --report-dir evals/reports/acme-smoke
```

The comparison command is used for retrieval ablations and model/prompt comparisons; the
difference is which recorded evaluator file each named configuration points at.

## Adding Queries

1. Add or edit corpus files under `evals/datasets/<name>/corpus/`.
2. Add labeled query rows to `queries.jsonl`.
3. Capture or author a recorded evaluation file for each gated config.
4. Run `atlas-eval run` and update baselines only when the new expected behavior is reviewed.

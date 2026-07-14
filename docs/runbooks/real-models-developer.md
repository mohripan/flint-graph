# Real Models Developer Runbook

Milestone 09 makes real providers the non-test default while keeping tests offline.

## Provider Defaults

Provider settings resolve by `ATLAS_ENV` when left unset:

| env | embeddings | answer | support |
|---|---|---|---|
| `test` | deterministic | deterministic | deterministic |
| `local` | Ollama `nomic-embed-text` | Anthropic | Anthropic |
| `staging` / `production` | OpenAI-compatible `text-embedding-3-small` | Anthropic | Anthropic |

Explicit `ATLAS_EMBEDDING_PROVIDER`, `ATLAS_QUERY_ANSWER_PROVIDER`, and
`ATLAS_QUERY_SUPPORT_PROVIDER` values always win.

## No-Cost Local Mode

For a fully offline/no-cost local run, set:

```powershell
$env:ATLAS_QUERY_ANSWER_PROVIDER = "deterministic"
$env:ATLAS_QUERY_SUPPORT_PROVIDER = "deterministic"
$env:ATLAS_EMBEDDING_PROVIDER = "deterministic"
```

Or use Ollama for embeddings/answer generation where supported:

```powershell
$env:ATLAS_EMBEDDING_PROVIDER = "ollama"
$env:ATLAS_QUERY_ANSWER_PROVIDER = "ollama"
$env:ATLAS_QUERY_SUPPORT_PROVIDER = "deterministic"
```

## Anthropic Runtime

Anthropic answer/support providers require one of:

```powershell
$env:ATLAS_ANTHROPIC_API_KEY = "<key>"
# or
$env:ANTHROPIC_API_KEY = "<key>"
```

The default answer and support model is `claude-opus-4-8`. Generation and support checking are
configured independently with `ATLAS_ANTHROPIC_ANSWER_MODEL`,
`ATLAS_ANTHROPIC_SUPPORT_MODEL`, and `ATLAS_ANTHROPIC_EFFORT`.

## Embedding Reindex Rule

Changing `ATLAS_EMBEDDING_PROVIDER`, `ATLAS_EMBEDDING_MODEL`, or
`ATLAS_EMBEDDING_DIMENSIONS` changes the vector space. Create a new retrieval index version and
run a backfill; do not reuse an active index version created for another embedding model.

## Fast Checks

```powershell
uv run pytest tests/unit/test_config.py tests/unit/test_anthropic_adapters.py
uv run pytest tests/unit/test_eval_cli.py tests/unit/test_evaluation.py
uv run atlas-eval run --dataset evals/datasets/acme-smoke --evaluations evals/reports/acme-smoke/deterministic-recorded.jsonl --experiment evals/experiments/acme-smoke.yaml --baseline evals/reports/acme-smoke/baselines.json --config-name deterministic
```

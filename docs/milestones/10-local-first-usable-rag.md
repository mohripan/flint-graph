# Milestone 10: Local-first usable RAG

## Status

Implemented.

Milestone 10 turns the existing backend query path into a local-first usable
workflow with explicit search readiness and query diagnostics. The milestone
does not add production authentication, document lifecycle diffing, deletion
propagation, tombstones, or replayable mutation logs.

## What changed

- Added an Ollama support-checking adapter behind the existing
  `SupportChecker` contract.
- Kept deterministic providers as the offline CI/default Compose path.
- Made Compose query and embedding providers overrideable for a local Ollama
  path.
- Added `GET /v1/search-readiness` for tenant-scoped active-index readiness.
- Added query-run creation rejection when the selected active retrieval index
  has no completed document coverage.
- Added compact `query_diagnostics` to query-run inspection responses.
- Updated the frontend to show search readiness, block questions before content
  is searchable, and surface run diagnostics.

## Search readiness

`GET /v1/search-readiness` resolves the tenant-visible active retrieval index
and summarizes PostgreSQL `document_index_coverages` for active document
versions. A workspace is query-ready only when at least one document version has
completed coverage for the selected active index.

Readiness reasons:

- `searchable`
- `no_active_index`
- `no_documents`
- `indexing_in_progress`
- `indexing_failed`
- `no_completed_coverage`

## Query diagnostics

Completed query runs expose a compact diagnostic summary as
`query_diagnostics`. It includes retriever candidate counts, failed retrievers,
retrieved/fused/reranked/context counts, skipped context count, support status
counts, abstention reason, answer provider, and support provider. The full
event stream and provenance APIs remain the detailed inspection path.

## Local Ollama path

Milestone 10 supports local no-cost model execution with Ollama:

- embeddings: `nomic-embed-text`, 768 dimensions;
- answer generation: `llama3.2` by default;
- support checking: `llama3.2` by default.

Switching embedding provider, model, or dimensions still requires creating a
compatible retrieval index version and backfilling documents.

## Validation

Required checks:

```powershell
uv run pytest
uv run ruff check .
uv run mypy
uv run flint-graph-eval run --dataset evals/datasets/acme-smoke --evaluations evals/reports/acme-smoke/deterministic-recorded.jsonl --experiment evals/experiments/acme-smoke.yaml --baseline evals/reports/acme-smoke/baselines.json --config-name deterministic
uv run alembic upgrade head --sql
docker compose config
cd frontend
npm run build
```

Manual local smoke uses the discrete mathematics PDF at the repository root.
See `docs/runbooks/local-ollama-rag.md` and
`docs/runbooks/frontend-e2e-qa-guide.md`.

## Deferred

Milestone 11 should handle changed sections, deletion propagation, tombstones,
graph invalidation rules, schema migration replay, incremental re-embedding,
and replayable indexing from a durable mutation log.

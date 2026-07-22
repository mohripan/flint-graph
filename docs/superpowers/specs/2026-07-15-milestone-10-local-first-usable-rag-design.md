# Milestone 10 Local-First Usable RAG Design

## Status

Approved planning design. Locked direction: Approach A, a local-first usability
milestone that makes FlintGraph usable end to end with Ollama before the larger
incremental change-lifecycle work begins.

## Summary

Milestone 10 makes the current product path usable and diagnosable from frontend
to backend:

```text
PDF upload
    -> ingestion
    -> chunking
    -> indexing with Ollama embeddings
    -> lexical/vector retrieval
    -> context packing
    -> Ollama answer generation
    -> Ollama support checking
    -> cited final answer or actionable diagnostics
```

The goal is not to add document diffing or replayable lifecycle semantics yet.
Those belong to Milestone 11. Milestone 10 instead removes the current gap where
a user can upload a document, ask a reasonable question, and receive only a
generic insufficient-evidence answer without knowing whether parsing, indexing,
retrieval, answer generation, or support checking failed.

Local development should work without cloud model credentials. Deterministic
providers remain required for offline tests and CI, but the product-oriented
local path should use Ollama for embeddings, answer generation, and support
checking.

## Architecture

Milestone 10 keeps PostgreSQL authoritative and continues using Neo4j and
OpenSearch as rebuildable retrieval projections. The primary architectural
change is that readiness and diagnostics become first-class API and UI concepts.

```text
document intake
    -> ingestion job status
    -> document version chunks
    -> index coverage for active retrieval index
    -> tenant search readiness
    -> query run
    -> retriever diagnostics
    -> context-pack diagnostics
    -> answer/support diagnostics
    -> frontend status and source panels
```

The frontend should not treat ingestion completion as equivalent to query
readiness. A document is ready to answer questions only after its active document
version has completed coverage for the active retrieval index visible to the
tenant. The Ask view should use that readiness state before creating a query
run.

Milestone 11 will cover changed sections, deletions, tombstones, graph
invalidation, schema migrations, re-embedding, and replayable indexing.

## Components

- Local provider path:
  Add an `OllamaSupportChecker` behind the existing `SupportChecker` protocol.
  `FLINT_GRAPH_QUERY_ANSWER_PROVIDER=ollama` and
  `FLINT_GRAPH_QUERY_SUPPORT_PROVIDER=ollama` must both be valid. Ollama embeddings
  should remain the local real-embedding path, with deterministic embeddings
  preserved for tests.

- Configuration and defaults:
  Clarify local configuration so a developer can intentionally run either the
  offline deterministic path or the local Ollama product path. Compose and
  `.env.example` should document the Ollama model requirements, embedding
  dimensions, and the need to create or backfill a compatible retrieval index
  when switching embedding providers.

- Readiness APIs:
  Add a tenant-scoped readiness summary that reports whether at least one
  document version is searchable under the active retrieval index. Include
  active index version identity, completed coverage count, running/failed
  coverage counts, and recent document-version status details.

- Query diagnostics:
  Persist and expose a compact diagnostic summary for each query run. It should
  include candidate counts by retriever, failed retrievers, fused and reranked
  counts, context record and token counts, skipped context count, citation
  repair counts, support status counts, abstention reason, answer provider,
  support provider, and model metadata.

- Frontend usability:
  The Documents view should distinguish uploaded, ingesting, ingested, indexing,
  searchable, failed, and cancelled states. The Ask view should show workspace
  search readiness, disable or warn before query creation when no searchable
  content exists, stream query progress, and show source/support diagnostics
  when an answer abstains.

- Discrete math smoke path:
  Add a documented manual flow using the root discrete mathematics PDF and
  questions such as "What is a set?", "What is a truth table?", and "What is
  discrete mathematics?" A successful local run produces natural answers with
  citations from the uploaded PDF.

## Data Flow

Upload still creates the document, immutable document version, ingestion job,
and outbox message as in the existing ingestion control plane. The frontend
tracks the ingestion job, then checks index coverage for the returned
`document_version_id` and the tenant-visible active retrieval index.

The Ask view resolves workspace readiness before creating a query run. If no
searchable content exists, the backend should return a clear conflict-style
problem response rather than running an empty query. The response should tell
the client whether the issue is no active index, no completed coverage,
in-progress indexing, or failed indexing.

During query execution, existing persisted query events remain the event stream
source. Milestone 10 extends the payloads or final inspection response with a
stable diagnostic summary so users and developers can see:

- which retrievers ran;
- how many candidates each retriever returned;
- whether candidates survived fusion and reranking;
- whether context records were packed;
- whether citations were repaired, dropped, or deduplicated;
- which claims were supported, partial, or unsupported;
- why an answer abstained.

The answer-generation path remains citation-only. Ollama answer generation
returns structured claims and citation IDs. Ollama support checking verifies
those claims independently against cited packed context before a final answer is
persisted.

## Error Handling

Insufficient context remains a valid final answer state, but it must no longer
be opaque. The UI should show a concise user-facing explanation and an
expandable technical summary.

Representative failure modes:

- No active retrieval index:
  The API rejects query creation with a readiness problem and points to index
  setup/backfill.

- Ingestion complete but indexing incomplete:
  The Documents view shows indexing progress, and the Ask view warns that the
  workspace is not searchable yet.

- Retrieval returns no candidates:
  The query can abstain, but diagnostics show zero lexical/vector/graph
  candidates rather than only a generic evidence message.

- Candidates exist but context is empty:
  Diagnostics show skipped context records and the packing reason, such as
  missing preview text, token budget, or record limit.

- Answer citations are invalid:
  Citation repair drops unknown markers, records the repair actions, and the
  frontend exposes the dropped-citation count.

- Support checking rejects claims:
  The final answer abstains when policy requires it, and diagnostics show the
  unsupported claim count and support checker method.

- Ollama is unavailable or a model is missing:
  Startup and runtime failures should be bounded and explicit, naming the
  provider, base URL, configured model, and the failed stage.

## Testing

Automated tests should remain offline by default. Deterministic providers stay
the CI path.

Required coverage:

- `OllamaSupportChecker` request shaping, response parsing, malformed response
  handling, and support-status adaptation using mocked HTTP responses.
- Provider factory wiring for deterministic, Ollama, and Anthropic answer and
  support providers.
- Readiness service and API behavior for no active index, no coverage, running
  coverage, failed coverage, and completed coverage.
- Query diagnostic summary persistence and API response mapping.
- Query creation conflict behavior when no searchable content exists.
- Frontend types and API client methods for readiness and diagnostics.
- Frontend build/typecheck for the new readiness and diagnostic UI.

Regression commands:

```powershell
uv run pytest
uv run ruff check .
uv run mypy
uv run flint-graph-eval run --dataset evals/datasets/acme-smoke --evaluations evals/reports/acme-smoke/deterministic-recorded.jsonl --experiment evals/experiments/acme-smoke.yaml --baseline evals/reports/acme-smoke/baselines.json --config-name deterministic
uv run alembic upgrade head --sql
docker compose config
cd frontend
npm run typecheck
npm run build
```

Manual local Ollama smoke:

1. Pull the configured Ollama embedding, answer, and support models.
2. Start Compose with the Ollama local-provider configuration.
3. Ensure an active retrieval index exists for the configured embedding model
   and dimensions.
4. Upload `001+Discrete+Mathematics+Oscar+Levin+4th+edition+free+book.pdf`.
5. Wait until the frontend marks the document searchable.
6. Ask:
   - "What is a set?"
   - "What is a truth table?"
   - "What is discrete mathematics?"
7. Confirm each successful answer has citations, source text, and supported
   claims. If an answer abstains, confirm diagnostics identify the failing
   stage.

## Documentation

Milestone 10 should add or update:

- `docs/milestones/10-local-first-usable-rag.md`;
- an ADR for local-first Ollama usability and support checking;
- a local Ollama developer runbook;
- a frontend/end-to-end QA guide;
- README setup instructions for deterministic versus Ollama local mode;
- AGENTS handoff updates;
- a short Milestone 11 planning note naming changed sections, deletions,
  tombstones, graph invalidation, schema migrations, re-embedding, and
  replayable indexing as the next lifecycle milestone.

## Non-Goals

Milestone 10 does not implement:

- changed-section diffing;
- deletion propagation;
- tombstone records;
- graph invalidation rules;
- schema migration replay;
- incremental re-embedding;
- replayable indexing from a durable mutation log;
- production authentication or authorization.

Those are explicitly deferred to Milestone 11.

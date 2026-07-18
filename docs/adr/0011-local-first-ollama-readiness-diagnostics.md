# ADR 0011: Local-first Ollama usability with readiness and diagnostics

## Status

Accepted.

## Context

Through Milestone 09, AtlasRAG could ingest, index, retrieve, orchestrate, and
faithfulness-check answers, but the end-user path was too opaque. A user could
upload a document and ask a question before indexing was complete, then receive
an insufficient-context answer without knowing whether ingestion, indexing,
retrieval, context packing, answer generation, or support checking was the
problem.

The local development path also needed to remain no-cost. Deterministic
providers are useful for CI and repeatable tests, but they are not acceptable as
the product-oriented local answer path.

## Decision

AtlasRAG keeps deterministic providers as the offline default and supports an
explicit local Ollama product path for embeddings, answer generation, and
support checking.

The API exposes search readiness as a first-class tenant-scoped read model. A
query run can be created only when the selected active retrieval index has at
least one completed document-version coverage row for the tenant. This avoids
running empty queries and makes the frontend able to distinguish ingesting,
indexing, searchable, failed, and cancelled document states.

Query diagnostics are stored as a compact derived summary in
`query_runs.metadata["diagnostics"]` and exposed as `query_diagnostics`. The
summary is built from persisted query events and terminal query-run fields, so
PostgreSQL remains authoritative and no new projection store is introduced.

## Consequences

- The frontend can block questions before content is searchable.
- Empty retrieval and support failures are diagnosable from query-run
  inspection.
- Existing event replay and provenance endpoints remain the detailed source.
- No database migration is needed for diagnostics because metadata is already a
  bounded JSON field.
- Switching embedding models still requires a new retrieval index version and
  backfill.

## Alternatives considered

Run queries even when no content is searchable. Rejected because it preserves
the opaque insufficient-context failure that Milestone 10 is intended to remove.

Add a dedicated diagnostics table immediately. Rejected for this milestone
because the summary is derived from already-persisted query events and terminal
run fields.

Make Ollama the hard-coded Compose default. Rejected because CI and first-run
local development still need a deterministic no-service path.

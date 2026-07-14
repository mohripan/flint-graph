# Milestone 08: Grounded answers, faithfulness, and provenance

## Status

In progress. Phases 1 through 6 are implemented.

Milestone 08 extends the Milestone 07 query orchestration path with grounded
answer generation, deterministic citation repair, claim support checking,
abstention, verified streaming output, persistence for answer faithfulness, and
tenant-scoped provenance APIs.

## Goal

Turn packed context into a synthesized answer that cites only supplied context,
checks every claim against its citations, abstains when support is weak, and
exposes an inspectable answer-to-source chain.

Target flow:

```text
packed context
    -> draft generation
    -> citation repair
    -> support checking
    -> abstention policy
    -> finalized answer and provenance
```

## Implemented Phase 1 Contracts

`src/atlas_rag/application/query_orchestration.py` now defines the
provider-neutral answer-faithfulness boundary:

- `AnswerDraft` for unverified provider output and raw citation markers;
- `CitationRepair` for normalized, dropped, and deduplicated citation markers;
- `SupportCheckClaim`, `SupportCheckRequest`, and `SupportCheckResult` for
  provider-neutral claim support checking;
- `AnswerClaim` and `AnswerFaithfulnessReport` for verified claims and compact
  faithfulness summaries;
- the `SupportChecker` protocol for deterministic and provider-backed support
  judges.

`src/atlas_rag/application/query_faithfulness.py` adds persistence-free Phase 1
helpers:

- `repair_claim_citations` normalizes markers such as `c1`, `[C1]`, and `(c1)`,
  maps them to packed context citation IDs, drops unknown markers, and removes
  duplicates while recording every action;
- `DeterministicSupportChecker` assigns `supported`, `partial`, or
  `unsupported` using lexical containment and token overlap against the cited
  context records;
- `evaluate_abstention` captures the first deterministic abstention policy
  checks for insufficient context, low supported-claim ratio, weak context
  relevance, and dropped citations.

`src/atlas_rag/config.py` adds safe defaults for the upcoming answer-generation
and support-checking providers. `deterministic` remains the default path.

## Current Boundaries

Phases 1 through 6 expose answer faithfulness, streaming, persistence, and
tenant-scoped provenance reads. Later phases add eval coverage, runbooks, and
manual verification notes.

## Implemented Phase 2 Provider Wiring

`src/atlas_rag/infrastructure/ollama.py` now includes
`OllamaAnswerGenerator`, a non-streaming answer provider that calls Ollama
`/api/generate` with a citation-only prompt and structured JSON schema. The
provider asks for `insufficient_context` plus claim text and citation IDs, then
adapts the draft into the existing `GeneratedAnswer` contract. Raw citation
markers and draft claims are retained in answer metadata for the later
faithfulness pipeline.

`src/atlas_rag/infrastructure/answer_generator_factory.py` adds
`create_answer_generator`, mirroring the embedding factory. It returns the
deterministic generator by default and the Ollama generator when
`query_answer_provider = "ollama"`. It also adds `create_support_checker`,
which returns the deterministic support checker and fails explicitly for the
future Ollama support judge.

`src/atlas_rag/api/dependencies.py` exposes an answer-generator dependency, and
the SSE query execution path passes that generator into the LangGraph runtime.
This makes `query_answer_provider = "ollama"` active for streamed API query
runs while preserving deterministic defaults for tests and direct service calls.

## Implemented Phase 3 Faithfulness Pipeline

`src/atlas_rag/application/services/query_faithfulness.py` adds the runtime
verification pipeline:

- reads structured draft claims from answer metadata when providers supply them;
- falls back to the legacy `GeneratedAnswer` shape for deterministic providers;
- repairs citation markers against the packed context;
- checks support with the configured `SupportChecker`;
- applies the abstention policy;
- returns a verified `GeneratedAnswer` plus an `AnswerFaithfulnessReport`.

`src/atlas_rag/application/services/query_answering.py` now verifies generated
drafts before appending answer events and completing a query run. The persisted
`answer_text` and `answer_citations` are the verified answer, not the raw
provider draft. Abstention returns the standard insufficient-context answer with
no citations and completes the run.

The LangGraph and API stream paths now pass the configured support checker and
threshold settings into answer generation. The deterministic generator remains
compatible through the legacy fallback path.

## Implemented Phase 4 Persistence

`migrations/versions/0011_answer_faithfulness.py` extends the query ledger with
faithfulness summary columns on `query_runs` and a `query_answer_claims` table.
Each completed query run can now store whether it abstained, the abstention
reason, supported and unsupported claim counts, the support method, and the
answer provider.

`query_answer_claims` stores one row per checked answer claim with resolved
`citation_ids`, support status, support score, reason, and method. Source text
remains in the context-pack records; claim rows store compact claim text and
resolved citation IDs for later provenance reads.

`src/atlas_rag/application/services/query_answering.py` now persists claim rows
and summary columns in the same transaction as the verified answer completion.
Claim persistence replaces prior rows for the run, keeping retries idempotent.

## Implemented Phase 5 Streaming And Events

`src/atlas_rag/application/query_orchestration.py` now includes the
faithfulness event types `support.checked`, `answer.abstained`, and
`answer.finalized`, plus an optional `StreamingAnswerGenerator` protocol for
providers that can emit provisional draft deltas.

`src/atlas_rag/application/services/query_answering.py` records provisional
`answer.delta` events with `provisional = true` when a generator implements the
streaming protocol. After verification, it emits the authoritative sequence:
final `answer.delta` with `provisional = false`, one `answer.citation` per
surviving citation, `support.checked`, optional `answer.abstained`,
`answer.finalized`, and then `query.completed`.

`OllamaAnswerGenerator` implements `stream_generate` by consuming Ollama
streaming JSONL responses from `/api/generate`, forwarding each `response`
fragment as a provisional delta, and validating the assembled structured draft
before the existing citation repair, support checking, abstention, and
persistence stages run.

## Implemented Phase 6 Provenance APIs

`src/atlas_rag/application/services/query_provenance.py` reads the authoritative
PostgreSQL state for a query run and assembles the answer-to-source chain from
existing records. It combines the completed `query_runs` answer summary,
`query_answer_claims` support decisions, and the latest
`query_context_pack_records` citation map.

`GET /v1/query-runs/{query_run_id}/provenance` returns the verified answer,
faithfulness summary, checked claims, and the context records backing each
surviving citation. `GET /v1/query-runs/{query_run_id}/citations/{citation_id}`
returns one citation record and the claims that cite it. Both endpoints apply
the existing tenant filter and return 404 for foreign runs or unknown
citations.

The Phase 6 response intentionally exposes the compact source IDs already
captured in context-pack records rather than deep-joining every possible source
type. This keeps the API stable across chunk, graph, and future candidate
sources while preserving the source chain needed for inspection.

## Expected Invariants

- Every surviving repaired citation maps to a packed context record.
- Unknown citation markers are dropped and recorded rather than trusted.
- Support checking is separate from answer generation.
- Deterministic support and abstention logic run without live model services.
- Persisted query events remain monotonic per run across provisional and final
  answer events.
- Provenance reads are tenant-scoped and are derived from PostgreSQL, not from
  Neo4j or OpenSearch projections.
- Provider-specific SDK objects do not leak into application contracts.

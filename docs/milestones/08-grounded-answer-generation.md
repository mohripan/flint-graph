# Milestone 08: Grounded answers, faithfulness, and provenance

## Status

In progress. Phases 1 through 3 are implemented.

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

Phases 1 through 3 do not add persistence columns, emit new faithfulness SSE
event types, stream live model tokens, persist per-claim support rows, or expose
provenance endpoints. Later phases adapt the verified report into the query
ledger and provenance APIs.

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

## Expected Invariants

- Every surviving repaired citation maps to a packed context record.
- Unknown citation markers are dropped and recorded rather than trusted.
- Support checking is separate from answer generation.
- Deterministic support and abstention logic run without live model services.
- Provider-specific SDK objects do not leak into application contracts.

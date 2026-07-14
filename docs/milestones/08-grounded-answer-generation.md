# Milestone 08: Grounded answers, faithfulness, and provenance

## Status

In progress. Phase 1 is implemented.

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

Phase 1 is intentionally application-only. It does not wire Ollama answer
generation, alter the LangGraph node, add persistence columns, emit new SSE
events, or expose provenance endpoints. Later phases adapt these contracts into
the query runtime and database ledger.

## Expected Invariants

- Every surviving repaired citation maps to a packed context record.
- Unknown citation markers are dropped and recorded rather than trusted.
- Support checking is separate from answer generation.
- Deterministic support and abstention logic run without live model services.
- Provider-specific SDK objects do not leak into application contracts.

# Answer Faithfulness Contract

## Purpose

The answer faithfulness contract defines how FlintGraph turns a packed context into
a grounded, cited, and inspectable answer. It sits above the Milestone 07 query
orchestration contract and refines its final `generate_answer` stage. It applies
once context packing has produced a `QueryContextPack` for a query run.

## Position In The Pipeline

```text
context.packed  (Milestone 07)
    -> draft generation      (citation-only, provider-backed)
    -> citation repair       (map / normalize / drop markers)
    -> support checking       (claim vs. cited context)
    -> abstention policy      (abstain on insufficient support)
    -> finalize + persist     (answer, claims, support, provenance)
```

Milestone 07 invariants remain in force: PostgreSQL is authoritative, tenant
filters apply on every path, deterministic providers keep tests offline, and no
provider SDK object leaks into application contracts.

## Application Contracts

New provider-neutral models live alongside the Milestone 07 contracts in
`flint_graph.application.query_orchestration`:

- `AnswerDraft` — unverified provider output: text, raw citation markers,
  `insufficient_context`, bounded metadata.
- `AnswerClaim` — one verified claim: index, text, resolved citation IDs,
  `support_status` (`supported` | `partial` | `unsupported`), score, reason,
  method.
- `CitationRepair` — one repair action: original marker, resolved citation ID or
  none, action (`kept` | `normalized` | `dropped_unknown` | `deduplicated`),
  reason.
- `AnswerFaithfulnessReport` — claims, repairs, supported/unsupported counts,
  abstention flag and reason, support method, bounded metadata.

New protocols and deterministic test doubles:

- `SupportChecker` — checks each claim against its cited context;
  `DeterministicSupportChecker` uses lexical overlap and containment.
- The existing `AnswerGenerator` protocol is retained. Providers return draft
  output; they do not certify their own grounding.

Deterministic implementations exist for repeatable local and CI coverage, not
for production answer quality.

## Generation Boundary

The answer model receives only the packed context, each record labeled with its
citation ID, plus the query and policy metadata. It must:

- answer only from the supplied context;
- attach at least one supplied citation marker to every claim;
- never introduce a marker that is not in the context list;
- set `insufficient_context` instead of fabricating when support is absent;
- never expose instructions, scores, prompts, or hidden reasoning.

Ollama drafts are constrained with structured `format` output, matching the
extraction adapter pattern. Foreign tenant context is never packed or supplied.

## Citation Repair Boundary

Repair is deterministic and runs before support checking. It normalizes marker
syntax, maps markers to real packed citation IDs, drops invented markers, and
deduplicates. Every action is recorded in `AnswerFaithfulnessReport.repairs`.
After repair, every surviving citation resolves to a `PackedContextRecord`; a
claim with no surviving citation is treated as unsupported.

## Support And Abstention Boundary

Support checking assigns each claim a status and score against the union of its
cited context. Abstention triggers when the model flags insufficient context,
when the supported-claim ratio is below `query_min_supported_claim_ratio`, when
top context relevance is below `query_min_context_relevance`, or when repair
removed all citations. An abstained run returns a safe, non-fabricating answer,
drops unsupported claims and their citations, records `abstain_reason`, and
completes — it does not fail.

## Persistence

Milestone 08 extends the Milestone 07 ledger:

- `query_runs` gains `abstained`, `abstain_reason`, `supported_claim_count`,
  `unsupported_claim_count`, `support_method`, and `answer_provider`.
- `query_answer_claims` stores one row per verified claim: run ID, tenant ID,
  claim index (unique per run), text, resolved citation IDs, support status,
  score, reason, and method.

Claims store compact text and resolved citation IDs. Source text stays in
context-pack records; provenance reads join through them. Chunk bodies are never
duplicated.

## Streaming Contract

Streaming follows stream-then-verify. Provisional `answer.delta` events
(`provisional: true`) stream model tokens for responsiveness. After generation,
repair, support, and abstention run on the full draft, then the authoritative
events are emitted: final `answer.delta` (`provisional: false`), one
`answer.citation` per surviving citation, `support.checked`, optional
`answer.abstained`, and `answer.finalized`. New `QueryStreamEventType` values are
`support.checked`, `answer.abstained`, and `answer.finalized`. Sequence numbers
stay monotonic per run. Only the verified answer is persisted; provisional deltas
are transient.

## Provenance APIs

Two tenant-scoped inspection endpoints expose grounding:

- `GET /v1/query-runs/{query_run_id}/provenance` — the answer, each claim with
  its citations, and, per citation, the packed context record and its underlying
  source IDs (chunk, document version, evidence span, entity, relationship) with
  the support decision.
- `GET /v1/query-runs/{query_run_id}/citations/{citation_id}` — a single
  citation resolved to its full source chain.

Foreign tenant query runs return 404. Responses never include foreign tenant
context.

The implemented Phase 6 API resolves provenance from PostgreSQL query-run
state, answer-claim rows, and context-pack records. Citation responses include
the packed context text, candidate ID, source IDs, record metadata, and the
claim support decisions that reference that citation. Deep source-specific joins
remain outside the Phase 6 contract so the same response shape works for chunk,
graph, and future candidate sources.

## Provider Selection

`create_answer_generator(settings)` returns the deterministic or Ollama
generator by `query_answer_provider`, mirroring `embedding_factory`. An optional
`create_support_checker(settings)` selects the deterministic checker or the LLM
judge by `query_support_provider`. `deterministic` is the default for both.

## Expected Invariants

Bare financial-value questions spanning multiple searchable documents can complete
with `ambiguous_financial_scope` and a clarification instead of a generated answer.
The bounded scope policy emits a persisted `query.clarification_required` event,
uses `scope-policy` for answer/support attribution, and creates no model usage,
claims or citations. Retrieval usage is still recorded. This narrow English policy
is not a general ambiguity detector; see
[ADR 0021](../adr/0021-clarifying-bare-financial-values.md).

- Every surviving citation maps to a packed context record.
- Every persisted answer claim carries a support decision.
- Repair records every change to model-emitted citation markers.
- Abstention completes the run without fabricated claims or citations.
- The persisted answer is always the verified answer, never a provisional draft.
- Support judging and generation are separate concerns behind distinct
  protocols; a generator never grades its own faithfulness.
- Provider and judge SDK objects never leak into contracts, persistence, or API
  schemas.
- All faithfulness and provenance reads apply tenant filters.

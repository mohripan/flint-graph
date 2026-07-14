# ADR 0008: Grounded answer generation with verified faithfulness

## Status

Accepted. Implemented in Milestone 08.

## Context

Milestone 07 delivered the full query-orchestration pipeline — classification,
entity linking, parallel retrieval, fusion, reranking, context packing, answer
generation, and SSE streaming — but shipped only the
`DeterministicAnswerGenerator`. That generator returns the first sentence of the
top packed context record and cites every packed record. The
`query_answer_provider = "ollama"` setting exists but is not wired: no code reads
it and no Ollama answer provider exists.

Consequently AtlasRAG can retrieve and pack context but cannot produce a
synthesized, trustworthy answer. It cannot say "I don't know", it has no defense
against a model citing context it did not use, and it cannot show why an answer
is grounded. Small local models (for example `gemma3:1b`, `llama3.2`) make this
worse: they frequently emit malformed or invented citation markers and
overclaim.

Milestone 08 needed a grounded answer path that is faithful to the packed
context, abstains when support is weak, streams responsively, and stays
inspectable — without abandoning the milestone's invariants (PostgreSQL
authoritative, deterministic providers for offline tests, no provider SDK
objects in application contracts).

## Decision

Milestone 08 adds a provider-backed grounded answer path built from four
composable stages behind provider-neutral contracts, plus provenance APIs.

1. **Citation-only generation.** The answer model receives only the packed
   context, each record labeled with its citation ID, and must attach a citation
   marker to every claim and use only the supplied markers. Ollama structured
   output (`format` JSON schema) constrains the draft, mirroring the existing
   `OllamaProposalExtractionModel`.

2. **Citation repair.** A deterministic post-processing step normalizes markers,
   maps them to real packed citation IDs, drops invented markers, and records
   every change. The model cannot introduce a citation that does not resolve to
   packed context.

3. **Support checking.** Each repaired claim is checked against the context it
   cites. The default `DeterministicSupportChecker` uses lexical overlap and
   containment for offline tests; an optional LLM judge (entailment prompt)
   sits behind the same `SupportChecker` protocol and is gated on settings.

4. **Abstention.** When the model flags insufficient context, when too few
   claims are supported, when top context relevance is below a floor, or when
   repair leaves a claim with no citations, the run abstains: it returns a safe
   non-fabricating answer, drops unsupported claims, records the reason, and
   still completes.

Generation and verification are **separated**: the `AnswerGenerator` produces a
draft; a faithfulness stage owns repair, support, and abstention. Providers
never certify their own grounding.

Streaming uses a **stream-then-verify** model: provisional tokens stream for
responsiveness (flagged `provisional`), then repair/support/abstention run on the
full draft and the authoritative answer, citations, support summary, and terminal
status are emitted and persisted. Only the verified answer is stored.

Persistence extends the Milestone 07 ledger: `query_runs` gains a faithfulness
summary and answer provider, and a new `query_answer_claims` table stores each
claim with its citations and support decision. Two tenant-scoped provenance
endpoints expose the answer-to-source chain.

Provider selection follows the existing `embedding_factory` pattern: a
`create_answer_generator(settings)` factory returns the deterministic or Ollama
generator by `query_answer_provider`, with `deterministic` remaining the default.

## Consequences

- Answers become synthesized, faithful, and inspectable; unsupported claims are
  removed or trigger abstention instead of being served confidently.
- The deterministic path keeps the whole suite runnable without live models; the
  Ollama path is opt-in through settings.
- Provider integrations stay behind protocols, so the generator and support
  judge can evolve (different models, remote APIs) without touching persistence
  or API schemas.
- Stream-then-verify introduces a short "provisional then corrected" window in
  the SSE stream that clients must handle; the persisted answer is always the
  verified one.
- The optional LLM judge roughly doubles model calls per query, so it stays off
  by default; the deterministic checker is the baseline.
- New per-claim rows add storage volume to the query ledger, reinforcing the
  retention decisions already flagged for a later hardening milestone.

## Alternatives Considered

### Wire Ollama with no faithfulness layer

Fastest path: swap the deterministic generator for an Ollama generator and stop.
Rejected — small local models hallucinate citations and overclaim, so answers
would look grounded while citing context they did not use, with no abstention and
no provenance. That regresses trust relative to the deterministic baseline.

### Let the generator self-report support and citations

Simpler to build, but a model grading its own faithfulness is unreliable and
unauditable, and it couples grounding logic to a specific provider. Separating
generation from verification keeps grounding provider-independent and testable.

### Verify fully before streaming anything

Buffer the complete generation, verify, then stream only the verified answer.
Cleaner event semantics, but it hides all model latency behind a blank stream
until verification finishes — the worst-feeling path on slow local models.
Stream-then-verify was chosen to keep the UX responsive while still persisting
only verified output.

### Compute provenance on demand instead of persisting claims

Deriving claim-to-source links at read time avoids new tables, but it would
require re-running repair and support checking (including any LLM judge) on every
inspection, making provenance non-deterministic and expensive. Persisting the
support decisions at answer time keeps provenance stable and cheap to read.

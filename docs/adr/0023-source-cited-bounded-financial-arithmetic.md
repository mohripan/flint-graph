# ADR 0023: independently verify source-cited financial arithmetic

Status: accepted for the bounded payments-table ratio described here.
Tracking: [#70](https://github.com/mohripan/flint-graph/issues/70).

## Decision

A model support judge approved a scale-error result for a public financial
question. Neither an additional instruction nor the same model's approval is
independent arithmetic verification. Introduce a pure, provider-neutral
calculation contract, and apply it outside the model judge.

The first supported request is English `average payments volume per transaction`,
with an explicit possessive company subject and requested dollars. Read an intact
pipe table from authoritative packed PostgreSQL chunk evidence, not lexical
previews or model-proposed operands. Require exact source identities, matching
chunk-text SHA-256, a company row matching the query subject, and exactly one
payments-volume and one total-transactions column with explicit scale headers.
Support thousand/million/billion/trillion scales. Never execute expressions or
instructions found in documents. Reject ambiguous/conflicting source rows;
deduplicate only identical source/version/chunk/hash/value-span identities.

`CitedOperand` identifies a decimal value, scale, dimension (money or transactions),
citation/context IDs, immutable source IDs/hash, and exact value/header/entity
spans relative to the packed chunk. Use decimal arithmetic at precision 50;
reject zero/nonpositive denominators and inexact/nonterminating results rather
than silently rounding. Numeric input syntax is bounded to 18 integer digits,
12 fractional digits and correctly grouped commas.

Before generation, a unique verified ratio may supply a bounded, typed calculation
hint in the answer request's server-owned policy. Both Ollama and Anthropic
generation prompts can consume it and must cite the original source ID. It is
not a new document/citation and adds no retrieval or provider call. Generation
prompt revision becomes `grounded-answer-v3`; support prompt remains unchanged.

After citation repair and model support checking, recompute independently using
only the result claim's own citations. Require one atomic monetary result, exact
scaled equality and the same company identity. Recognized incompatible units,
negation, missing/uncited/legacy evidence and ambiguous quantities fail closed.
This check can reject a model-approved claim but cannot promote a claim that
the support model rejects. A hint does not bypass verification. Never rewrite
the draft's numbers after generation. If a requested ratio has no verified result,
abstain for the whole answer (`financial_arithmetic_unverified`) instead of
rendering only the otherwise-supported premises.

## Audit and boundaries

Original draft claim text remains in tenant-scoped `query_answer_claims`, including
rejected results. Store preparation hints and detailed calculation/provider-judgment
audit in reserved `query_runs.metadata` keys `arithmetic_preparation` and
`arithmetic_verification`, in the existing answer transaction. The latter includes
typed operand spans, computed result, verification reason and original model
judgments. Keep the normal faithfulness-report metadata compact; detailed audit
is separate from its 4-KiB envelope. Check at most eight derived claims and refuse
larger calculation answers. Existing 100-claim/100-record/4,000-character limits
bound source and judgment audit. Do not export quotations/provider reasons in
logs, SSE summaries, metrics or redacted nightly reports.

No new schema, service, provider, external executor or Temporal workflow is
introduced. Current tenant-scoped context packing and provenance/source-lifecycle
inspection remain the boundary. The verifier does not fetch foreign, deleted or
raw-source content on its own. It verifies immutable packed evidence, not a fresh
source-lifecycle lock extending across inference. Source deletion during a query
and all-provider invocation budgeting remain separate lifecycle/platform concerns.

## Deliberate limitations

This is a bounded division tool, not a financial semantic judge, universal table
reader or full arithmetic language. It does not implement additions, differences,
percentage changes, multiple requested ratios, rounded/repeating-decimal policy,
OCR/PDF table reconstruction, inferred missing units, cross-currency conversion,
period alignment or contradiction resolution. Currency/report-period attribution
still requires evidence and the existing support boundary; money/count dimensions
are not independent proof of USD or the report year. Other query phrasing,
non-possessive subjects and split/incomplete tables cannot gain this verifier's
approval. Broader source-backed structured financial analysis remains #89.

Source text is untrusted. Regex-based English result/qualifier recognition is
conservative but is not a complete negation, linguistic or adversarial-content
detector; OWASP threat modeling/runtime policy remains #80/#81. Retain independent
quality rubrics, tests and the final support gate even when calculation checks pass.

## Verification and rollback

Regress the source-backed wrong scale result against an always-approving provider
fixture, plus correct differently scaled/company cases, malformed/inexact numbers,
uncited/legacy evidence, conflicting hashes, wrong units, negation and premises-only
answers. Verify SQLite and PostgreSQL audit persistence and foreign-run denial.
Run a fresh real-model public-API/provenance/nightly capture and inspect saved
answer rendering in the frontend. Preserve old failing captures and thresholds.

Rollback requires reverting calculation preparation/checking and prompt revision
together; do not leave a hint without the independent final guard. Existing
schema/provenance readers need no destructive migration, and old query audits
remain valid historical records.

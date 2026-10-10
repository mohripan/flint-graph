# ADR 0021: Clarify bare financial-value questions across reports

- Status: accepted; narrow English rule implemented
- Date: 2026-10-10
- Issue: [#60](https://github.com/mohripan/flint-graph/issues/60)

## Decision

A bare value question such as “What was revenue?” is not permission to choose
arbitrary companies and periods from a multi-report workspace. Before answer
generation, recognize a deliberately bounded set of English past-tense scalar
financial requests. When at least two distinct authorized documents have active
versions and completed coverage in the selected index, return a clarification.
An explicit valid document/version filter narrows that check. A supplied year
removes the period prompt but not the company/document prompt.

Persist `query.clarification_required`, policy version `financial-scope-v1`, and
missing scope dimensions. Finalize as an abstained query with reason
`ambiguous_financial_scope`, no factual claims or citations, and provider/support
method `scope-policy`. Do not call answer/support models or invent usage events.
Retrieval still runs and its actual usage remains accounted for. The frontend
labels this as a request to narrow the question, not a failed model response.

## Alternatives and limits

Grounding alone cannot resolve user intent: figures may be individually supported
but still answer a different company's or period's question. A general model-based
ambiguity classifier would add latency, nondeterminism and another quality gate;
it is not introduced by this change. Definitions, summaries, comparisons and
questions naming a company do not match this narrow rule.

This is not complete semantic disambiguation. It does not infer company/period
from conversation memory, qualify every named-company question, or guarantee that
a single document contains one reporting period. Scoped/single-document questions
continue through normal citation and support checks. Multi-turn clarification
requires the separately planned conversation contract in ADR 0019/#62.

Rejected generated claims remain in audit/provenance and quality metrics, even
when not rendered. Neither thresholds nor baselines are relaxed to make this
change pass. Acceptance includes tenant/index/lifecycle tests, zero-model-call
clarification, real API/SSE/provenance checks, browser reopen and a fresh unchanged
nightly evaluation.

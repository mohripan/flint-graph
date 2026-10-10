# ADR 0022: Bounded retrieval for explicit coordinated sources

- Status: accepted for narrow English syntactic planning
- Date: 2026-10-10
- Issue: [#59](https://github.com/mohripan/flint-graph/issues/59)

## Context

The pinned public financial cross-report question lost Philip Morris evidence
before fusion or packing. A single mixed lexical query favored Devon and unrelated
reports. Splitting the question alone still failed: the trailing instruction to
identify which figure belongs to which company pushed the correct income chunk
to lexical rank 10, outside that clause's five-result allocation. The same clause
without the presentation instruction retrieved it at rank 1.

## Decision

Recognize two or three distinct capitalized possessive source names separated by
`and`, `versus` or `vs`. Persist the original question unchanged, the derived
`retrieval_queries`, and `decomposition_method=coordinated-possessive-v1` in the
classification ledger. Generation, support checking, linking and reranking retain
the original question. An unsupported classification never expands retrieval.

Remove only a narrowly recognized comma-delimited instruction to identify which
figure/value/number belongs or corresponds to which company/document/source from
the retrieval clauses. Other qualifiers, including tax effects, remain. This is
not general semantic rewriting, financial intent inference or entity resolution.

Lexical and vector retrieval split each source's existing candidate allowance
across clauses; remainders go to earlier clauses. Ten candidates become five per
clause for two sources or four/three/three for three. Calls within one owned read
session run sequentially, while independent retriever sources still run in
parallel. Graph retrieval uses the original question and existing accepted links.
This bounds candidate counts, not request counts: two/three clauses make four/six
lexical/vector calls, and the existing vector adapter embeds each clause. There
is no new planning-model call. Real embedding-call usage/reservations and broader
cost controls require separate accounting/budget qualification; this deployment
uses deterministic embeddings.

Trim over-returning external results to the allocated limit, round-robin clause
results, and deduplicate per retriever by existing candidate identity. Preserve
the highest normalized score, stable parent rank and all matching
`retrieval_clause_indices`. Existing fusion, authorized source filters,
PostgreSQL evidence hydration, citation repair and support gates are unchanged.
If any clause call fails, its retriever follows the existing required/partial
failure policy; no extra retries or candidate allowance are created.

## Alternatives and limits

Increasing every clause to the full parent limit inflates resource use and obscures
the existing budget. Hardcoded companies, source IDs, ticker aliases or expected
values would fit the evaluation rather than fix planning. A general model-driven
planner or lead-agent strategy requires the separate M18/M20 contracts and budgets.

This rule does not cover lowercase/multilingual names, implicit pronouns, arbitrary
dependency questions or more than three coordinated sources. Repeated names,
unsplittable questions and insufficient candidate allowances retain the original
query. Existing reranking/token packing may still omit a requested part; this is
not a complete-facet guarantee, conversation memory or durable execution. The
runtime guard also rejects malformed/oversized derived-clause metadata.

## Verification

Tests reproduce source loss with the original single request and recover both
literal evidence records and supported citations with decomposition. PostgreSQL
and SQLite checks cover two/three clauses, parent allocations, duplicate and
over-returning results, unsupported queries and required/partial failure policy.
Keep the strict public two-source gold, labels, rubrics and thresholds unchanged.
Record live model/corpus evidence and all gates in the delivery report before
closing the implementation issue.

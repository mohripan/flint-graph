# Milestone 15: useful answers and explainable failures

Status: in progress. Tracking: [issue #1](https://github.com/mohripan/flint-graph/issues/1).
See the [roadmap](../ROADMAP.md) for the complete acceptance criteria.

## Verified claim policy

[Issue #10](https://github.com/mohripan/flint-graph/issues/10) fixes publication of
partially supported draft statements. Final verified output retains only claims
with a `supported` decision; partially supported and unsupported decisions remain
inspectable in the faithfulness report and persisted claim records. Their
citations are omitted from final output when no retained claim uses them.

An answer with zero supported claims abstains even if the configured minimum
supported-claim ratio is zero. Mixed drafts may retain fully supported facts if
the existing ratio policy passes. This is claim filtering, not yet the planned
question-coverage model for partial answers in Milestone 20.

Regression tests cover a correct headquarters claim alongside an office claim
with an unevidenced date/profitability, and zero-threshold abstention. Provider
support decisions are still the verification boundary; a deterministic lexical
checker is an offline fixture, not proof of production semantic accuracy.

## Offline OIDC integration harness

[Issue #11](https://github.com/mohripan/flint-graph/issues/11) makes the shared
OIDC fixture explicitly select deterministic extraction, embeddings, answers,
and support checking. It retains local OIDC behavior without requiring hosted
credentials or a developer `.env`. Production provider defaults are unchanged.
The original complete suite had 17 credential-validation failures in this
fixture; explicitly selecting offline providers resolves those failures.

## Document-scoped queries

[Issue #12](https://github.com/mohripan/flint-graph/issues/12) implements query
filters for `document_id`, `document_version_id`, and `chunk_id`. Document/version
IDs must be UUID strings; chunk IDs must be nonempty strings of at most 100
characters. Unsupported query filters return 422. The primitive retrieval APIs
retain their separate existing filter contract.

Lexical/vector search receives the restrictions, and returned chunks are checked
again before candidate creation. Out-of-scope hits cannot reach an answer even
when a projection returns them. Graph relationship summaries may combine sources,
so filtered queries currently use only lexical/vector evidence; graph retrieval
returns no relationships until source-scoped relationship evidence is supported.
Unfiltered graph behavior is unchanged. A scoped query without evidence abstains.

## Parallel retrieval sessions

[Issue #13](https://github.com/mohripan/flint-graph/issues/13) gives each API
retrieval task its own read session. The execution session alone writes run state,
candidates, and events after gathering results. Independent network retrieval
remains concurrent, and one retriever ending its read transaction cannot roll
back another retriever or the query's event ledger.

The application graph accepts an optional `retrieval_session_factory`. Callers
using independent read sessions must commit source/setup records before running
retrieval. The graph commits pending run state and `retrieval.started` before
opening those read sessions. Existing transactional service tests may omit the factory to read their
uncommitted fixtures; production API execution always supplies it.

Query API regressions can additionally run against PostgreSQL by setting
`FLINT_GRAPH_PG_INTEGRATION=1`, with optional `FLINT_GRAPH_PG_TEST_URL`. Each
fixture owns a unique schema which it removes afterward, avoiding production
table mutation. Offline SQLite remains the default test backend.

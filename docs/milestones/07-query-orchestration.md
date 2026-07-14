# Milestone 07: Query orchestration and streaming answers

## Status

In progress. Phases 1 through 7 are implemented: application-level query
contracts, provider-neutral protocols, deterministic classifier/reranker/answer
generator, query orchestration settings, the PostgreSQL query-run ledger, and
deterministic query classification/entity linking services, plus the first
LangGraph query orchestration runtime for parallel retrieval, candidate fusion,
deterministic reranking, citation-ready context packing, and deterministic
answer generation. API routes, SSE streaming, and graph expansion hydration are
still planned.

## Goal

Build a LangGraph-backed query state machine that classifies user questions,
links query mentions to canonical entities, runs retrievers in parallel, fuses
and reranks candidates, expands graph context, packs citation-ready context, and
streams grounded answers.

Target flow:

```text
query request
    -> PostgreSQL query run
    -> LangGraph orchestration
    -> query classification
    -> entity linking
    -> lexical/vector/graph retrieval
    -> fusion + graph expansion + reranking
    -> context packing
    -> streamed answer with citations
```

## Scope

Included:

- query-run ledger and persisted stream events;
- provider-neutral classifier, reranker, and answer-generator contracts;
- deterministic providers for tests;
- query-time entity linking against canonical graph entities;
- LangGraph state machine with explicit node boundaries;
- parallel lexical, vector, and graph retriever orchestration;
- candidate fusion and deduplication;
- bounded graph expansion;
- reranking;
- token-budgeted context packing with citation maps;
- answer generation and SSE streaming APIs;
- query inspection APIs;
- evaluation fixtures and manual QA guidance.

Excluded:

- production authentication and authorization beyond existing tenant routing;
- chat memory across many turns;
- autonomous tool use beyond retrieval and graph expansion;
- Kafka-based query event fan-out;
- production prompt-management UI;
- full observability dashboards;
- human-in-the-loop answer review workflows.

## Implemented Phase 1 Contracts

`src/atlas_rag/application/query_orchestration.py` defines the current
application contract boundary. It includes:

- query classification requests, labels, retrieval plans, and strategy metadata;
- query-time entity link decisions;
- retriever candidate summaries with bounded source IDs and metadata;
- token-budgeted context packs with citation-preserving records;
- generated answers, answer citations, and structured stream event envelopes;
- provider-neutral protocols for query classification, reranking, and answer
  generation;
- deterministic providers for repeatable local tests.

The Phase 1 contracts are intentionally persistence-free. They do not create
query-run rows, expose API schemas, or depend on LangGraph. Later phases should
adapt these contracts into database records and streaming responses without
leaking provider SDK objects into application services.

## Implemented Phase 2 Ledger

`migrations/versions/0010_query_run_ledger.py` and
`src/atlas_rag/infrastructure/db/models.py` add:

- `query_runs`;
- `query_run_events`;
- `query_run_linked_entities`;
- `query_run_candidates`;
- `query_context_packs`;
- `query_context_pack_records`.

`src/atlas_rag/application/services/query_runs.py` provides the persistence
boundary for creating tenant-scoped query runs, loading runs by tenant,
transitioning run status, appending monotonic per-run events, recording
classification summaries, and storing linked-entity, candidate, and context-pack
summaries. The service validates that query runs use an active retrieval index
version visible to the tenant.

Query-run state changes use `QueryRunStatus` and explicit transition rules in
`atlas_rag.domain.transitions`. Foreign-tenant query-run reads return
`NotFoundError`.

## Implemented Phase 3 Classification And Linking

`src/atlas_rag/application/services/query_planning.py` adds the deterministic
query planning service boundary:

- `classify_query_run` loads a tenant-scoped query run, invokes the
  provider-neutral classifier contract, persists classification metadata, and
  appends `query.classified`;
- `link_query_entities` loads a tenant-scoped query run, links query mentions
  against tenant-scoped active canonical entities and aliases, persists
  accepted/ambiguous/rejected link decisions, and appends `entities.linked`.

Entity linking reuses the existing entity-resolution normalization logic.
Exact normalized canonical-name or alias matches are accepted when they resolve
to one entity, ambiguous when they resolve to multiple entities, and rejected
when no tenant-scoped match exists. Foreign tenant aliases and entities are not
considered.

## Implemented Phase 4 LangGraph Retrieval Orchestration

`src/atlas_rag/application/services/query_orchestration.py` adds the first
LangGraph-backed query state machine. The implemented graph runs:

```text
initialize_run
    -> classify_query
    -> link_entities
    -> plan_retrieval
    -> retrieve_parallel
    -> fuse_candidates
    -> rerank_candidates
    -> pack_context
    -> generate_answer
```

The graph starts a queued query run, persists `query.started`, reuses the Phase
3 classification and entity-linking services, derives enabled retrievers from
the structured retrieval plan, and runs configured lexical, vector, and graph
retrievers concurrently. Retriever adapters are injected through small
application protocols so runtime infrastructure can be added without coupling
LangGraph nodes to OpenSearch, Neo4j, or provider SDK objects.

`retrieve_parallel` persists raw candidate summaries with
`persist_query_candidate` and appends `retrieval.started`,
`retrieval.progress`, and `retrieval.completed` events. Graph retrieval is
conservative: it is skipped unless accepted entity links are available. A
required retriever failure transitions the run to `failed` with bounded error
metadata; successful retrieval continues into the Phase 5 fusion and reranking
nodes.

## Implemented Phase 5 Fusion And Reranking

`src/atlas_rag/application/services/query_fusion.py` adds deterministic
candidate fusion and persisted reranking. Fusion loads raw
`query_run_candidates`, groups duplicates by candidate type plus source IDs,
computes a weighted score from the classified retriever weights, normalized
score, and reciprocal rank, and writes `fusion_score` back to the raw candidate
rows. It appends `fusion.completed` with input, fused, and deduplicated counts.

Reranking uses the provider-neutral `QueryReranker` protocol and defaults to
`DeterministicQueryReranker`. It reranks the fused representative candidates,
persists `rerank_score`, `rerank_rank`, and reasons on selected candidate rows,
and appends `rerank.completed`. Successful Phase 5 execution continues into
the Phase 6 context-packing node.

## Implemented Phase 6 Context Packing

`src/atlas_rag/application/services/query_context_packing.py` adds deterministic
context packing over reranked candidates. The packer loads tenant-scoped
`query_run_candidates`, selects rows by `rerank_rank`, skips candidates without
preview text, estimates tokens with a simple word-count heuristic, and enforces
the configured token budget and maximum record count.

The service creates stable `PackedContextRecord` values with `ctx-0001` style
context IDs and `c1` style citation IDs, persists them through
`persist_query_context_pack`, and appends `context.packed`. The graph now
returns context record and token counts. Successful Phase 6 execution continues
into the Phase 7 answer-generation node.

## Implemented Phase 7 Answer Generation

`src/atlas_rag/application/services/query_answering.py` adds deterministic
answer generation and completion persistence. It loads the latest persisted
context pack, reconstructs the provider-neutral `QueryContextPack`, invokes the
`AnswerGenerator` protocol, and defaults to `DeterministicAnswerGenerator`.

The service transitions the query run from `running` to `completed`, persists
`answer_text` and structured `answer_citations`, and appends
`query.completed`. If generation fails, it transitions the run to `failed` with
bounded error details and a `query.failed` event. Phase 7 does not implement
SSE transport yet, so `answer.delta` streaming remains planned.

## Architecture

PostgreSQL remains authoritative for AtlasRAG control-plane state. Milestone 07
adds query-run records, query events, linked-entity decisions, candidate
summaries, context-pack manifests, answer metadata, and bounded failure details.

LangGraph coordinates the query runtime. Its graph state stays compact and
carries IDs, decisions, counters, and summaries. Source text and graph records
are loaded inside nodes from PostgreSQL and from existing retrieval services.

Milestone 06 services remain the retrieval substrate:

- OpenSearch lexical search for full-text and metadata-filtered chunk recall;
- Neo4j vector search through the active retrieval index version;
- PostgreSQL canonical graph neighborhoods for authoritative bounded traversal.

## Query Run Lifecycle

Expected statuses:

- `queued`: the run was accepted but graph execution has not started;
- `running`: at least one graph node has started;
- `completed`: answer generation completed and final metadata was persisted;
- `failed`: execution stopped with bounded error details;
- `cancelled`: caller or server cancellation stopped execution.

Every stream event has a query-run ID, tenant ID, sequence number, type, payload,
and timestamp. Clients can use the SSE stream for live output and the query-run
inspection endpoint for post-run debugging.

## Public APIs

Planned endpoints:

- `POST /v1/query-runs`;
- `GET /v1/query-runs/{query_run_id}`;
- `GET /v1/query-runs/{query_run_id}/events`;
- optional `POST /v1/query` as a thin non-streaming convenience wrapper.

All endpoints are tenant-scoped. Foreign tenant query runs return 404.

## Expected Invariants

- Query APIs always apply tenant filters.
- Query orchestration uses an active retrieval index version visible to the
  tenant.
- Model output never directly mutates canonical graph state.
- Answer generation only consumes packed context and policy metadata.
- Every citation in an answer maps to a packed context record.
- Context packing never includes foreign tenant data.
- Stream event sequence is persisted and monotonic per query run.
- Provider-specific SDK objects do not leak into application contracts.

## Known Risks

- LangGraph graph-state design can become difficult to reason about if large
  records are carried between nodes.
- Answer streaming needs careful cleanup so failed client connections do not
  leave misleading run states.
- Reranking and answer generation can hide retrieval defects unless candidate
  summaries and rank movement are persisted.
- Query-time entity linking may surface ambiguous entities and needs conservative
  defaults.
- Context packing quality will likely require iteration after real query evals.

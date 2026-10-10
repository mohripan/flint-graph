# Query Orchestration Contract

Current versioned chunk packing rehydrates authoritative PostgreSQL evidence;
see [Milestone 17 progress](../milestones/17-retrieval-and-evidence.md). Search
previews are ranking inputs, not the final answering text. Missing/stale/inactive
versioned chunks are skipped, with explicit reason counts in `context.packed`.

## Purpose

The query orchestration contract defines how FlintGraph turns a tenant-scoped user
query into a grounded streaming answer. It sits above the Milestone 06 retrieval
index contract.

## Inputs

A query request contains:

- tenant ID from local routing headers;
- query text;
- optional retrieval index version ID;
- optional metadata filters;
- optional candidate, graph, and context limits;
- optional streaming preference.

`X-Tenant-ID` remains local tenant routing, not authentication.

## Phase 1 Application Contracts

The implemented application contract lives in
`flint_graph.application.query_orchestration`. It is provider-neutral and does
not depend on persistence, FastAPI, LangGraph, Ollama, or Docker.

Current contract groups:

- `QueryClassificationRequest`, `QueryClassification`, and
  `QueryRetrievalPlan`;
- `QueryEntityLink`;
- `QueryCandidate`;
- `QueryContextPack` and `PackedContextRecord`;
- `GeneratedAnswer` and `AnswerCitation`;
- `QueryStreamEvent`;
- `QueryClassifier`, `QueryReranker`, and `AnswerGenerator` protocols.

The deterministic classifier, reranker, and answer generator are test doubles
that implement these protocols. They are meant for repeatable local and CI
coverage, not for production answer quality.

## Query Run Ledger

Each accepted query creates a PostgreSQL `query_runs` row. The query run is the
authoritative inspection record for orchestration state, selected retrieval
index version, classification, answer metadata, timing counters, and bounded
errors.

`query_run_events` stores the ordered stream event sequence. Events are useful
both for live SSE clients and for post-run debugging.

Supporting records store linked entities, candidate summaries, and context-pack
manifests. These records should preserve source identities and compact metadata
instead of copying all chunk text.

The implemented ledger tables are:

- `query_runs`;
- `query_run_events`;
- `query_run_linked_entities`;
- `query_run_candidates`;
- `query_context_packs`;
- `query_context_pack_records`.

Query-run events are unique by `(query_run_id, sequence)` and are appended by
the application service with a monotonic sequence per run. Candidate summaries
are unique by `(query_run_id, dedupe_key)`. Context packs are unique by
`(query_run_id, pack_version)`.

## LangGraph State

LangGraph state is the runtime state machine payload. It should contain:

- query run ID and tenant ID;
- selected retrieval index version ID;
- classification and retrieval strategy;
- linked entity IDs and compact link decisions;
- retriever branch configuration;
- candidate summaries;
- fused and reranked candidate references;
- packed context manifest reference;
- answer and citation metadata.

Graph state must not become a bulk transport for large chunk text, raw provider
responses, credentials, or SDK objects.

The implemented Phase 4 graph is intentionally small:

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

It uses `langgraph.graph.StateGraph` and stores only compact run state:
tenant ID, query-run ID, selected retrieval index version, classification,
linked entity IDs, enabled retrievers, candidate limits, counters, and bounded
errors. After successful answer generation it transitions the query run to
`completed`; failed answer generation transitions it to `failed`.

## Classification

The classifier returns a structured result:

- label;
- confidence;
- retrieval strategy;
- retriever weights and limits;
- entity-linking requirement;
- graph-expansion requirement;
- partial-failure policy.

The initial labels are `factoid`, `summary`, `relationship`, `comparison`,
`exploratory`, and `unsupported`.

The implemented deterministic classification service persists the classifier
output to `query_runs.classification_*` fields and appends a `query.classified`
event.

## Entity Linking

Entity linking maps query mentions to canonical entities. It may use existing
normalization, aliases, lexical/trigram candidate search, and provider-backed
disambiguation.

Accepted links can seed graph retrieval. Ambiguous links are persisted for
inspection but are not used for expansion unless the query strategy explicitly
allows it.

The implemented deterministic linker uses existing entity-resolution
normalization and tenant-scoped active canonical entities plus aliases. Exact
normalized canonical-name or alias matches become accepted links when unique,
ambiguous links when multiple active tenant entities match, and rejected links
when no tenant-scoped match exists.

## Retriever Outputs

All retrievers return candidate records with:

- retriever source;
- candidate type;
- source IDs;
- raw score and normalized score;
- rank;
- text or graph summary suitable for downstream selection;
- citation-capable source metadata;
- tenant ID and retrieval index version where applicable.

Lexical and vector candidates come from Milestone 06 services. Graph candidates
come from bounded PostgreSQL canonical graph traversal.

The Phase 4 orchestration service accepts retriever implementations through
application-level protocols for lexical, vector, and graph retrieval. The graph
invokes the enabled retrievers concurrently and persists each returned
`QueryCandidate` into `query_run_candidates` with the original source, rank,
scores, source IDs, and compact metadata.

Graph retrieval is only enabled when entity linking produced at least one
accepted canonical entity ID. If a configured strategy marks partial retrieval
as disallowed, any retriever failure transitions the run to `failed` and stores
bounded retriever error details.

## Fusion And Reranking

Fusion deduplicates candidates by stable source identity and combines retriever
signals with query-strategy weights. Reranking reorders fused candidates for
answer usefulness.

Both stages must record enough metadata to explain rank movement during
inspection.

The implemented Phase 5 fusion service groups duplicate candidates by candidate
type plus source IDs. It computes `fusion_score` from the classified retriever
weight, normalized score, and reciprocal rank, then persists the score on the
raw candidate rows. Duplicate rows keep the same group fusion score, while
reranking is applied to one deterministic representative per group.

Reranking uses the provider-neutral `QueryReranker` protocol and defaults to
the deterministic term-overlap reranker. Selected representative rows receive
`rerank_score`, `rerank_rank`, and explanatory reasons. The graph appends
`fusion.completed` and `rerank.completed` events before leaving the run
`running` for later context-packing and answer-generation nodes.

## Context Packing

Context packing selects a bounded set of chunks, evidence spans, entities, and
relationships for generation. The packer must:

- enforce token budget;
- preserve citation IDs;
- prefer source diversity;
- record truncation and exclusion reasons;
- reject foreign tenant records.

The answer generator can only use the packed context and policy metadata.

The implemented Phase 6 packer selects reranked candidates in rank order,
requires non-empty preview text, enforces token budget and maximum record
limits, and persists the result in `query_context_packs` plus
`query_context_pack_records`. Context IDs and citation IDs are deterministic
within a pack. Phase 6 uses candidate previews as the initial context text;
future source hydration can replace previews with full chunk, evidence, entity,
and relationship records without changing the persistence contract.

## Answer Generation

Answer generation consumes only the packed context and policy metadata. It must
not read arbitrary raw retrieval state or mutate canonical graph state.

The implemented Phase 7 answer service loads the latest persisted context pack,
reconstructs the provider-neutral application contract, calls an injected
`AnswerGenerator`, and defaults to the deterministic answer generator. It
appends answer, citation, faithfulness, and finalized events, persists
`answer_text` and structured citation metadata on `query_runs`, appends
`query.completed`, and marks the run `completed`. When generation raises an
error, the run is marked `failed` with bounded error details and `query.failed`.

## Query APIs

The implemented API surface is tenant-scoped:

- `POST /v1/query-runs` creates a queued query run against an explicit or
  resolved active retrieval index version.
- `GET /v1/query-runs/{query_run_id}` returns the inspectable run state,
  classification summary, counters, answer, citations, and bounded errors.
- `GET /v1/query-runs/{query_run_id}/events` returns the persisted event list.
- `GET /v1/query-runs/{query_run_id}/events/stream` starts execution for queued
  runs and streams the persisted event sequence as Server-Sent Events.

The streaming endpoint emits only committed query-run events. The graph commits
after node boundaries in the streaming path and pushes newly committed events to
the SSE response, preserving the same sequence that later inspection endpoints
return. Lexical and vector API adapters use an immutable retrieval-index
snapshot inside parallel retriever branches so concurrent retrievers do not
share a database session.

## Saved question history

`GET /v1/query-runs` returns a recent-first array, ordered by creation timestamp
then UUID descending. `limit` defaults to 50 and is bounded to 1–200. Optional
`q` is a case-insensitive literal question substring (maximum 200 characters);
`%`, `_` and the escape character are not user-supplied wildcards. Optional
`before_id` selects rows strictly older than that run's timestamp/UUID tuple.
The cursor must resolve in the authorized tenant; unknown or foreign IDs return
404. Use the last row ID as the next cursor; an empty page ends traversal. New
insertions do not shift older pages. There is no frozen cross-page snapshot:
deleted cursors require refreshing history and search results reflect live data.

Reading a run and its provenance does not start another model invocation. Failed
and pending runs are incomplete outcomes, not empty successful answers. Reopening
history is independent of current search readiness. Conversation IDs, prior-turn
context and chained conversation execution are not implemented; #62 tracks them.
Question substring search currently scans tenant-filtered rows rather than
claiming a full-text indexed history search; large-history benchmarking is future
work. Existing list response fields remain compatible.

## Streaming Events

SSE event types include:

- `query.started`;
- `query.classified`;
- `entities.linked`;
- `retrieval.started`;
- `retrieval.progress`;
- `retrieval.completed`;
- `fusion.completed`;
- `graph.expanded`;
- `rerank.completed`;
- `context.packed`;
- `answer.delta`;
- `answer.citation`;
- `support.checked`;
- `answer.abstained`;
- `answer.finalized`;
- `query.completed`;
- `query.failed`;
- `query.cancelled`.

Events are persisted with monotonic per-run sequence numbers.

## Failure Modes

- Classification failure fails the query run.
- One retriever may fail without failing the run only when the selected strategy
  allows partial retrieval.
- Fusion, context packing, and answer generation failures fail the run.
- Client disconnect should not mark a completed run as failed if generation
  continues successfully.
- Foreign tenant resources return 404 or are filtered out according to endpoint
  contract.

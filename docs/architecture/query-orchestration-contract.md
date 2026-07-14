# Query Orchestration Contract

## Purpose

The query orchestration contract defines how AtlasRAG turns a tenant-scoped user
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
`atlas_rag.application.query_orchestration`. It is provider-neutral and does
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

## Fusion And Reranking

Fusion deduplicates candidates by stable source identity and combines retriever
signals with query-strategy weights. Reranking reorders fused candidates for
answer usefulness.

Both stages must record enough metadata to explain rank movement during
inspection.

## Context Packing

Context packing selects a bounded set of chunks, evidence spans, entities, and
relationships for generation. The packer must:

- enforce token budget;
- preserve citation IDs;
- prefer source diversity;
- record truncation and exclusion reasons;
- reject foreign tenant records.

The answer generator can only use the packed context and policy metadata.

## Streaming Events

SSE event types should include:

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

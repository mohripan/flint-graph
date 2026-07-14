# Milestone 06: Retrieval indexes and backfills

## Status

In progress. Phases 1 through 5 are implemented.

Milestone 06 builds the retrieval substrate for AtlasRAG. It introduces
provider-neutral embeddings, versioned retrieval indexes, Neo4j vector indexes,
OpenSearch lexical indexes, metadata-filterable primitive search endpoints,
graph traversal primitives, and restartable backfills.

Milestone 07 will build query planning and orchestration on top of these
primitives.

## Goal

Materialize document chunks and resolved graph state into rebuildable retrieval
indexes.

Target flow:

```text
active document chunks + canonical graph
    -> embedding generation
    -> PostgreSQL retrieval index ledger
    -> Neo4j vector projection
    -> OpenSearch lexical projection
    -> primitive search and traversal APIs
    -> backfill/reconcile operations
```

## Scope

Included:

- provider-neutral embedding interface and infrastructure adapters;
- deterministic embeddings for tests;
- PostgreSQL index versions, chunk embeddings, and backfill jobs;
- Neo4j vector index migrations and vector-bearing projection;
- OpenSearch mappings, aliases, and lexical projection;
- separate Temporal indexing workflow;
- restartable backfill and reconcile paths;
- public primitive lexical, vector, graph traversal, index-version, and coverage
  APIs.

Excluded:

- LangGraph query state machine;
- query classification;
- query-time entity linking;
- parallel retriever orchestration;
- fusion, reranking, context packing, and answer generation;
- SSE query streaming;
- Kafka-based event fan-out.

## Implementation Progress

Completed in Phase 1:

- provider-neutral embedding request/result models and asynchronous protocol;
- deterministic embedding model for repeatable tests and local validation;
- stable embedding configuration hash using canonical JSON and SHA-256;
- Ollama embedding adapter behind the application protocol;
- OpenAI-compatible embedding adapter shape behind the same protocol;
- indexing, embedding, OpenSearch, and active index-version settings.

Completed in Phase 2:

- PostgreSQL retrieval index ledger models and migration;
- retrieval index version scope/status enums;
- chunk embedding persistence model with idempotency constraint;
- backfill job persistence model with progress and checkpoint fields;
- partial unique indexes enforcing one active global version and one active
  version per tenant;
- transition service for create, activate, deprecate, and fail operations.

Completed in Phase 3:

- OpenSearch local Compose service and internal service URL wiring;
- deterministic chunk index mapping for text search and metadata filters;
- lexical chunk record contract and stable OpenSearch document IDs;
- idempotent bulk upsert and delete payload builders;
- OpenSearch HTTP adapter for index creation, alias updates, bulk writes, and
  search;
- tenant-filtered lexical search body builder.

Completed in Phase 4:

- Neo4j `:Chunk` retrieval node schema migration;
- default 384-dimensional Neo4j vector index for `Chunk.embedding`;
- lookup indexes for chunk tenant/index/document-version identity;
- vector projection service with stable chunk node IDs;
- idempotent chunk vector upsert and bounded delete helpers;
- safe Cypher generation for versioned vector indexes.

Completed in Phase 5:

- separate `IndexDocumentVersionWorkflow` for indexing one document version into
  one retrieval index version;
- ingestion workflow integration for `disabled`, `optional`, and `required`
  indexing modes;
- document index coverage persistence with status, planned chunk count,
  projection counts, timestamps, and bounded failure metadata;
- batched chunk embedding persistence tied to retrieval index version and chunk
  hash;
- idempotent Neo4j vector and OpenSearch lexical projection calls from indexing
  activities;
- worker registration for indexing workflow and activities.

No backfill execution or primitive retrieval API behavior is active yet.

## Datastore Roles

PostgreSQL remains the system of record. It stores document chunks, canonical
graph state, retrieval index versions, chunk embedding records, and backfill
state.

Neo4j remains a rebuildable projection. Milestone 06 extends it with
vector-bearing retrieval records and vector indexes while preserving the existing
canonical graph projection.

Phase 4 adds separate `:Chunk` retrieval nodes for vector projection. Canonical
`:Entity` graph projection remains unchanged.

OpenSearch is introduced as the lexical retrieval projection. It stores
searchable chunk records with analyzers, relevance scoring, and metadata
filters. Its physical indexes are versioned behind aliases.

Phase 3 adds the OpenSearch adapter, mapping, alias, bulk payload, and search
request builders. Later phases call these builders from indexing workflows and
public retrieval APIs.

MinIO continues to store immutable raw and derived artifacts. Embedding or index
manifests may be added only when content-addressed snapshots are useful.

## Index Versioning

An index version captures the retrieval contract that produced indexed records:

- embedding provider and model;
- vector dimension;
- embedding configuration hash;
- chunking/schema version;
- lexical mapping/schema version;
- Neo4j vector index/property names;
- OpenSearch physical index and alias names;
- status and activation metadata.

Changing any retrieval-shaping input creates a new index version and requires
backfill. Active endpoints use the active version by default but may accept an
explicit version for inspection.

The ledger supports global and tenant-scoped versions. Global versions have no
tenant ID. Tenant-scoped versions require a tenant ID. The database and service
both enforce one active global version and one active version per tenant.

## Ingestion And Backfill

Indexing should run in a separate Temporal workflow after ingestion has produced
chunks and extraction/resolution work has committed.

Phase 5 adds `IndexDocumentVersionWorkflow`. The ingestion workflow prepares an
indexing target after parsing, chunking, and extraction finish:

- `disabled` mode completes ingestion without starting indexing;
- `optional` mode completes ingestion first, then starts the indexing workflow
  as a follow-up so indexing failures cannot fail a completed ingestion job;
- `required` mode waits for the indexing workflow before marking ingestion
  complete, so indexing failures fail the ingestion job and document version.

Workflow history carries only document/index IDs, batch indexes, and counters.
Chunk text and vectors are loaded inside activities from PostgreSQL.

Document-version coverage is stored in `document_index_coverages`. Each row is
unique by retrieval index version and document version, and records status,
chunk count, embedded/vector/lexical counts, timestamps, and bounded errors.

Backfills use the same indexing services as ingestion. A backfill scans active
document versions missing the target version, embeds their chunks, persists
embedding rows, updates Neo4j vectors, upserts OpenSearch records, and records
checkpoint progress.

All writes are idempotent by tenant, document version, chunk ID, chunk hash, and
index version.

Phase 2 stores backfill job state but does not yet execute backfill workflows.

## Primitive APIs

Milestone 06 exposes low-level retrieval APIs:

- index version listing;
- index coverage checks;
- backfill start/status;
- lexical search against OpenSearch;
- vector search against Neo4j;
- bounded entity neighborhood traversal.

These APIs return ranked records and graph context. They do not synthesize final
answers.

## Expected Invariants

- PostgreSQL is authoritative for index/version state.
- Neo4j and OpenSearch can be rebuilt from PostgreSQL.
- Embeddings are tied to chunk hashes and index versions.
- Only one active retrieval index version exists for a scope.
- Foreign tenant resources remain invisible through tenant-scoped APIs.
- Optional indexing failures do not block ingestion; required indexing failures
  fail the document version.
- Primitive search endpoints always apply tenant filters.

## Known Risks

- Neo4j vector index capabilities vary by Neo4j version, so migrations should
  stay explicit and integration-tested.
- OpenSearch adds a new local service and operational surface area.
- Provider-specific embedding APIs differ in batching, dimensions, and error
  formats. The application contract must hide those differences.
- Rebuilding large indexes will need careful batching and progress checkpoints.

# Retrieval Index Contract

## Purpose

AtlasRAG retrieval indexes turn authoritative PostgreSQL chunks and graph state
into queryable lexical, vector, and graph-traversal primitives.

Milestone 06 defines the index contract. Milestone 07 will use it for query
planning, retriever orchestration, fusion, reranking, context packing, and
answer generation.

## Source Records

The primary indexing input is `document_chunks` for active document versions.
Each chunk has:

- tenant ID;
- document ID;
- document version ID;
- stable chunk ID;
- chunk index;
- text;
- chunk hash;
- source element IDs;
- heading path;
- page fields;
- source offsets;
- metadata.

Canonical entities, relationships, and evidence spans provide graph context and
future citation links. PostgreSQL remains authoritative for all source records.

## Embedding Provider Contract

The application depends on a provider-neutral asynchronous embedding protocol.
The protocol accepts bounded batches of text plus model/config metadata and
returns vectors, dimensions, and provider metadata.

The Phase 1 application contract lives in `atlas_rag.application.embeddings`.
It defines `EmbeddingInput`, `EmbeddingBatchRequest`, `EmbeddingVector`,
`EmbeddingBatchResult`, and the `EmbeddingModel` protocol. Requests validate
unique input IDs, bounded batch size, provider name, model name, and vector
dimension. Results validate that every returned vector matches the declared
dimension.

Embedding configuration hashes are generated from canonical JSON containing the
contract version, provider, model, dimension, and provider config. Hashes use
the existing `sha256:<hex>` format so index versions can compare retrieval
shaping inputs deterministically.

Provider-specific SDK objects, request payloads, error shapes, and credentials
must not leak into application services, persistence models, workflow contracts,
or API schemas.

Required implementations:

- deterministic embedding model for tests;
- Ollama local development adapter;
- OpenAI-compatible adapter shape so additional providers can be added behind
  the same contract.

## Index Versions

A retrieval index version identifies a complete retrieval contract:

- scope: global or tenant;
- embedding provider;
- embedding model;
- vector dimension;
- embedding config hash;
- chunking/schema version;
- lexical schema version;
- Neo4j vector index/property names;
- OpenSearch physical index and alias names;
- status: `building`, `active`, `deprecated`, or `failed`;
- activation and error metadata.

Only active versions are used by default search endpoints. Explicit version IDs
may be used for inspection, backfill validation, and rollbacks.

Index versions are stored in PostgreSQL in `retrieval_index_versions`. Versions
are either global or tenant-scoped. A global version must have no tenant ID; a
tenant-scoped version must have one. Partial unique indexes enforce that only
one global version and one version per tenant can be active at a time.

Valid version statuses are `building`, `active`, `deprecated`, and `failed`.
The application transition service creates versions in `building`, activates a
building version while deprecating any active version in the same scope,
deprecates building or active versions, and records bounded failure metadata for
non-active versions.

## Chunk Embeddings

A chunk embedding is tied to:

- tenant ID;
- document ID;
- document version ID;
- chunk ID;
- chunk hash;
- retrieval index version;
- vector dimension.

The same chunk text and version can be retried without duplicate active rows.
If the chunk hash changes, the previous embedding is stale and must not be
reused for the new chunk.

Chunk embeddings are stored in PostgreSQL in `chunk_embeddings`. The
idempotency key is retrieval index version, document version, chunk ID, and
chunk hash. Vector values are persisted as JSON until a later phase decides
whether a PostgreSQL vector extension is needed; Neo4j remains the intended
vector search projection for Milestone 06.

## Neo4j Vector Projection

Neo4j stores retrieval projection nodes or properties with:

- tenant ID;
- document/document-version/chunk identity;
- chunk hash;
- index version identity;
- vector property for the active embedding contract;
- optional links to canonical entities when provenance supports it.

Vector index names and vector property names are versioned. Rebuilding a Neo4j
vector projection must be possible from PostgreSQL chunk embeddings.

Phase 4 projects vectors onto separate `:Chunk` nodes. A chunk node ID is stable
by tenant ID, retrieval index version ID, document version ID, and chunk ID.
Nodes store tenant, document, document-version, chunk, chunk-hash, and retrieval
index-version identity fields plus a configurable vector property. The default
schema migration creates `Chunk.id` uniqueness, lookup indexes for
tenant/index-version and document-version/chunk queries, and a default
384-dimensional cosine vector index on `Chunk.embedding`.

Version-specific vector indexes can be generated from retrieval index version
metadata. Because Neo4j identifiers cannot be parameterized, index names,
labels, and vector property names are validated before being interpolated into
Cypher.

## OpenSearch Lexical Projection

OpenSearch stores chunk records in versioned physical indexes behind aliases.
Each document contains:

- tenant ID;
- document ID;
- document version ID;
- chunk ID;
- chunk hash;
- title and source metadata;
- chunk text;
- heading path;
- page fields;
- entity or evidence metadata when available;
- active/deleted status;
- index version identity.

Text fields are mapped for lexical relevance. Tenant, document, version, source,
page, status, and other metadata fields are mapped for exact filters.

Search requests must always include a tenant filter.

Phase 3 implements the lexical projection contract in
`atlas_rag.application.services.lexical_projection` and
`atlas_rag.infrastructure.opensearch`. OpenSearch document IDs are stable by
tenant, document version, and chunk ID. Bulk upsert and delete operations use
NDJSON actions with those stable IDs so retries replace or remove the same
records.

The default chunk mapping indexes `title`, `text`, and `heading_path` as text
fields, stores tenant/document/version/chunk/index identifiers as keywords, and
keeps page fields numeric. Search body generation always includes a `tenant_id`
term filter before adding optional metadata filters.

## Backfill And Reconcile

Backfills scan active document versions missing a target index version. They
embed chunks, persist embeddings, update Neo4j vector projection, upsert
OpenSearch records, and checkpoint progress.

Reconcile operations repair projection drift by replaying PostgreSQL source
state into Neo4j and OpenSearch.

Both paths are idempotent.

Backfill jobs are stored in PostgreSQL in `index_backfill_jobs` with optional
tenant, document, and document-version scope, status, counters, checkpoint, and
bounded last-error metadata. Phase 2 persists this state; execution is added in
later phases.

## Primitive Retrieval APIs

Milestone 06 APIs expose:

- index versions;
- index coverage;
- backfill start and status;
- lexical search;
- vector search;
- graph neighborhood traversal.

Responses contain ranked chunks, scores, metadata, entity context, and traversal
records as applicable. They do not generate final natural-language answers.

## Failure Modes

- Provider failure records bounded error metadata and follows indexing mode.
- OpenSearch projection failure leaves coverage incomplete and can be retried.
- Neo4j projection failure leaves coverage incomplete and can be retried.
- Backfill failure preserves checkpoint and last error.
- Failed index versions are not used by default endpoints.

## Security Boundary

`X-Tenant-ID` remains local tenant routing, not authentication. Every retrieval
API and projection query must apply tenant scoping. Foreign tenant resources
return 404 or empty result sets according to the endpoint contract.

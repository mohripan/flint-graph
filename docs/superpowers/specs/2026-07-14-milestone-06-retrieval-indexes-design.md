# Milestone 06 Retrieval Indexes Design

## Status

Approved planning design.

## Summary

Milestone 06 builds FlintGraph's retrieval substrate. PostgreSQL remains
authoritative. Neo4j gains versioned vector indexes as a rebuildable projection.
OpenSearch is introduced as the rebuildable lexical projection. A separate
Temporal indexing workflow handles document-version indexing and backfills.

Milestone 07 will consume these primitives for LangGraph query planning,
retriever orchestration, fusion, reranking, context packing, and answer
generation.

## Architecture

```text
active chunks + canonical graph
    -> provider-neutral embedding contract
    -> PostgreSQL retrieval index ledger
    -> Neo4j vector projection
    -> OpenSearch lexical projection
    -> primitive search and traversal APIs
```

PostgreSQL stores retrieval index versions, chunk embeddings, and backfill state.
Neo4j stores graph and vector retrieval projection. OpenSearch stores lexical
chunk documents with metadata filters.

## Components

- Embedding protocol and provider adapters.
- Retrieval index version service.
- Chunk embedding persistence service.
- Neo4j vector projection service.
- OpenSearch lexical projection service.
- Temporal indexing workflow and activities.
- Backfill/reconcile workflow or process.
- Primitive API routes for index versions, coverage, backfills, lexical search,
  vector search, and entity neighborhoods.

## Data Flow

New document versions are indexed after ingestion has produced chunks and
committed graph-related work. Backfills scan existing active document versions
that lack a target index version. Both paths use the same embedding and
projection services and are idempotent by tenant, document version, chunk ID,
chunk hash, and retrieval index version.

## Error Handling

Indexing supports `disabled`, `optional`, and `required` modes. Provider,
OpenSearch, and Neo4j failures record bounded error metadata. Required indexing
can fail a document version; optional indexing leaves coverage incomplete and
recoverable by retry/backfill. Failed index versions are not active by default.

## Testing

Testing covers deterministic embeddings, version transitions, idempotent
embedding persistence, stale chunk hashes, OpenSearch mapping/filter payloads,
Neo4j vector Cypher generation, tenant isolation, backfill checkpoints, and
gated live OpenSearch/Neo4j integration tests.

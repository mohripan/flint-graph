# ADR 0006: Rebuildable retrieval indexes

## Status

Accepted. Implemented in Milestone 06.

## Context

Milestones 03 through 05 created durable document chunks, provenance-rich
staged extraction proposals, canonical graph state, and an idempotent Neo4j
graph projection. Retrieval and query-time orchestration remain intentionally
out of scope.

AtlasRAG now needs searchable retrieval substrates before adding a LangGraph
query planner. The proposed platform architecture includes Neo4j for graph and
vector retrieval and OpenSearch for lexical retrieval. The existing codebase
already treats PostgreSQL as authoritative and Neo4j as rebuildable, which is a
good fit for index versioning and backfills.

## Decision

Milestone 06 will introduce rebuildable retrieval indexes:

- PostgreSQL stores retrieval index versions, chunk embedding records, and
  backfill/indexing job state.
- Neo4j stores vector-bearing retrieval projection records and versioned vector
  indexes.
- OpenSearch stores versioned lexical chunk indexes behind aliases.
- Embedding generation uses a provider-neutral application protocol with
  infrastructure adapters.
- A separate Temporal indexing workflow handles document-version indexing and
  backfills.
- Primitive search and traversal APIs expose lexical, vector, graph
  neighborhood, index-version, coverage, and backfill operations.

PostgreSQL remains the system of record. Neo4j and OpenSearch are projections
that can be rebuilt from PostgreSQL chunks, graph state, and index-version
records.

## Consequences

- Retrieval indexes are inspectable, versioned, and backfillable.
- Provider/model/dimension changes do not silently mutate active retrieval
  behavior; they create a new version.
- OpenSearch introduces a new service dependency and operational runbook.
- Neo4j vector search becomes part of the graph projection surface.
- Milestone 07 can compose stable lexical, vector, and graph primitives instead
  of inventing storage contracts during query orchestration.
- Kafka remains deferred until independent event consumers or volume require it.

## Alternatives Considered

### Store lexical and vector indexes only in OpenSearch

This would reduce the number of retrieval systems, but it would not satisfy the
Neo4j vector-index direction and would make graph-native vector retrieval less
natural.

### Keep lexical search in PostgreSQL

PostgreSQL full-text search and trigram indexes would be simpler operationally.
However, the target architecture includes OpenSearch, and Milestone 06 is the
right point to establish the lexical projection before query orchestration.

### Add Kafka before indexing

Kafka can support independent indexing consumers later. For Milestone 06, the
existing transactional outbox and Temporal workflows are sufficient and avoid
adding an event platform before there is a concrete fan-out need.

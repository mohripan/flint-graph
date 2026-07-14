# ADR 0007: LangGraph query orchestration with traceable query runs

## Status

Proposed for Milestone 07.

## Context

Milestone 06 created rebuildable retrieval indexes and primitive retrieval APIs:
lexical search, vector search, and bounded graph neighborhoods. AtlasRAG now
needs an end-to-end query path that can plan retrieval, combine multiple context
sources, and produce grounded answers with citations.

The query path will include LLM-assisted stages such as classification,
reranking, and answer generation. These stages need auditability, deterministic
test doubles, tenant scoping, and bounded failure behavior.

## Decision

Milestone 07 will use LangGraph for query orchestration and PostgreSQL for
AtlasRAG query-run traceability.

The LangGraph state machine will:

- classify the query;
- link query mentions to canonical entities;
- plan lexical, vector, and graph retriever branches;
- run eligible retrievers in parallel;
- fuse and deduplicate candidates;
- expand graph context under strict bounds;
- rerank candidates;
- pack a bounded citation-ready context;
- generate and stream the final answer.

PostgreSQL will store query runs, stream events, linked-entity decisions,
candidate summaries, context-pack manifests, answer metadata, and bounded error
details. LangGraph coordinates execution but does not replace AtlasRAG's
control-plane ledger.

Provider-specific model integrations will sit behind application protocols for
classification, reranking, and answer generation. Deterministic implementations
will support repeatable tests.

## Consequences

- Query behavior becomes inspectable and debuggable after streaming completes.
- Retrieval, ranking, context packing, and answer generation can evolve behind
  stable application contracts.
- LangGraph can express parallel retrieval branches and explicit state-machine
  transitions without forcing query traces into logs only.
- PostgreSQL query events add storage volume and require retention decisions in
  a later hardening milestone.
- The system needs careful graph-state discipline so large chunk text does not
  move through every node.

## Alternatives Considered

### Stateless LangGraph orchestration

This would be faster to implement, but failures and poor answers would be hard
to debug because classification decisions, retriever results, rank movement,
context packing, and stream events would live mostly in logs.

### Temporal workflow for query execution

Temporal is already used for durable background work. Query execution is a
latency-sensitive request path with streaming output, so Temporal would add
operational complexity and less natural SSE behavior for this milestone.

### Hand-written async pipeline without LangGraph

A hand-written pipeline would reduce dependency surface, but it would make
branching, parallel retrieval, state inspection, and future graph evolution more
ad hoc.

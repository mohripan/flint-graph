# Milestone 07 Query Orchestration Design

## Status

Approved planning design. Locked direction: Approach A, a LangGraph query
orchestration layer with PostgreSQL-traceable query runs and streaming answer
generation.

## Summary

Milestone 07 turns the Milestone 06 retrieval primitives into an end-to-end RAG
query path. A LangGraph state machine classifies the query, links entities,
runs lexical/vector/graph retrievers in parallel, fuses and reranks candidates,
expands graph context, packs a bounded citation-ready context, and streams an
answer.

PostgreSQL remains authoritative for query-run traces, selected plans, linked
entities, candidate summaries, packed context manifests, answer metadata, and
bounded failures. LangGraph coordinates the runtime flow; it does not replace
the AtlasRAG control-plane ledger.

## Architecture

```text
query request
    -> query run ledger
    -> LangGraph state machine
    -> classification
    -> entity linking
    -> parallel lexical/vector/graph retrievers
    -> fusion
    -> graph expansion
    -> reranking
    -> context packing
    -> streamed answer generation
    -> query run inspection
```

The graph consumes existing Milestone 06 services for lexical search, vector
search, and bounded entity neighborhoods. Provider-specific model APIs live at
the infrastructure edge behind application contracts.

## Components

- Query API routes for run creation, final response retrieval, and SSE event
  streaming.
- Query orchestration contracts for state, classification, entity links,
  retrieval candidates, fused results, context packs, citations, answers, and
  stream events.
- LangGraph builder and node implementations.
- Deterministic classifier, linker, reranker, and generator for tests.
- Provider adapters for LLM-backed classification, reranking, and generation.
- PostgreSQL query-run ledger and event persistence.
- Context packer that enforces token and citation budgets.

## Data Flow

The API creates a query run for one tenant and starts the graph. The graph state
contains IDs, compact query metadata, intermediate decisions, and candidate
summaries. Large source text is loaded inside nodes from PostgreSQL and M6
retrieval services.

Streaming clients receive structured lifecycle events and answer chunks. The
same events are persisted so a completed or failed run can be inspected after
the stream closes.

## Error Handling

Every graph node records bounded failure details. Retriever failures can degrade
when the plan allows partial retrieval, but classification, context packing, and
answer generation failures fail the run. Streamed failures use explicit event
types and persist the terminal run status.

## Testing

Tests cover graph transitions, deterministic model behavior, tenant isolation,
entity-linking decisions, parallel retriever fan-out, fusion and deduplication,
graph expansion bounds, reranking stability, context budget enforcement,
citation integrity, SSE event order, and failure persistence.

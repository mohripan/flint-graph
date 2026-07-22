# ADR 0005: Staged extraction proposals before canonical resolution

## Status

Accepted. Implemented in Milestone 05.

## Context

Milestone 04 proved the local GraphRAG control plane: extracted entities and claim triples flow into PostgreSQL, deterministic resolution creates canonical entities and relationships, and Neo4j is rebuilt from PostgreSQL. That path works, but the extraction boundary is too thin for trustworthy retrieval and citation.

The current model output can supply entity names, triples, and chunk IDs. It does not produce inspectable extraction runs, verified evidence spans, provider invocation records, stable staged proposal IDs, or proposal-level candidate records. The current `entity_mentions` and `claims` tables therefore mix two concerns: model-derived proposal staging and canonical resolution input.

FlintGraph needs a stronger trust boundary before query-time RAG is added. A model should propose facts, but FlintGraph must verify evidence, assign durable identities, persist provenance, and decide deterministically what reaches the canonical graph.

## Decision

Milestone 05 introduced staged extraction proposals as the boundary between chunks and canonical resolution.

The ingestion worker runs extraction after chunking. The activity assembles bounded batches of stored chunks, calls a provider-neutral structured extraction model, validates schema and local references, verifies quote evidence against stored chunk text, derives stable IDs and local offsets, writes a content-addressed manifest, and persists extraction runs, invocations, evidence spans, staged entities, staged relations, staged claims, and proposal candidates transactionally.

Canonical resolution consumes ready staged proposals directly. Candidate generation creates explainable records and never mutates canonical graph state by itself. Auto decisions, review decisions, merges, and unmerges remain deterministic and auditable.

The existing Milestone 04 `entity_mentions` / `claims` bridge is superseded as the primary resolution input. Those tables may be removed, renamed, or retained only as compatibility/internal projections if implementation needs them temporarily.

PostgreSQL remains authoritative. Neo4j remains an idempotent projection of canonical PostgreSQL state, not a target for extraction output.

## Consequences

- The model cannot mutate canonical entities, relationships, or Neo4j.
- Every accepted staged record has a deterministic evidence chain back to chunk text, document version, and immutable raw source.
- Provider-specific APIs stay at the infrastructure edge.
- Extraction runs and invocations become inspectable, retryable, and auditable.
- Candidate records explain why a staged proposal may match another proposal or canonical entity.
- Milestone 04 graph APIs and tests may change because the primary input model changes.
- Implementation effort increases now, but the system avoids carrying a long-term adapter around a premature mention/claim design.

## Alternatives Considered

### Add staged extraction but keep the current mention bridge

This would be faster and preserve more tests, but it creates two overlapping concepts: staged extracted entities and entity mentions. It also makes future citation and evaluation work depend on translation layers.

### Redesign the entire canonical graph

This maximizes freedom, but the current canonical graph posture is still sound: PostgreSQL is authoritative, Neo4j is a projection, and merges are reviewable and reversible. The weak boundary is extraction-to-resolution, not the whole graph.

### Skip provenance and build query-time RAG next

This would create visible user value sooner, but answers would be built on weak evidence. Retrofitting exact citations after a query layer exists is higher risk.

# Knowledge Graph Contract

## Purpose

AtlasRAG turns per-document extraction output into a resolved, provenance-backed knowledge graph. PostgreSQL is the system of record; Neo4j is an idempotent projection. This contract describes the entities, aliases, mentions, claims, relationships, scoring, banded decisions, and provenance introduced in Milestone 04.

Milestone 05 is planned to supersede the Milestone 04 mention/claim extraction bridge with staged extraction proposals and verified evidence spans. The canonical graph posture in this contract remains directionally valid; the upstream extraction input model is expected to change.

## Datastore Roles

- PostgreSQL stores the authoritative control plane and resolved graph.
- Neo4j stores a projection of active entities and relationships, tagged with `tenant_id` on every node and edge.
- MinIO stores the extraction artifact that mentions and claims derive from.

## Entities And Aliases

A canonical entity is a resolved, deduplicated real-world entity for a tenant.

- `canonical_entities`: `entity_type`, `canonical_name`, `normalized_name`, `status` (`active` / `merged` / `deprecated`), `merged_into_id` (self-reference for soft merges), `support_count`.
- `entity_aliases`: alternate surface forms for an entity, unique per `(tenant_id, canonical_entity_id, normalized_form)`, with a `source` of `extraction`, `merge`, or `manual`.

Entity types reuse the extraction taxonomy: `person`, `organization`, `place`, `concept`, `other`.

## Mentions

A mention is one occurrence of an entity-like surface in a document version.

- `entity_mentions`: `surface_text`, `normalized_text`, `entity_type`, `chunk_ids`, `resolved_entity_id` (nullable until resolved), `resolution_status` (`pending` / `resolved` / `review` / `rejected`), plus provenance: `source_artifact_id`, `prompt_hash`, `response_hash`.

Mentions are derived from a version's extraction artifact and are idempotent per version.

## Claims

A claim is a per-version asserted `(subject, predicate, object)` triple.

- `claims`: `subject_mention_id`, `predicate`, `object_mention_id` (nullable), `object_literal` (nullable), `evidence_chunk_ids`, `status` (`pending` / `linked` / `rejected`).

A claim links its object to an entity mention when the object surface matches an extracted entity; otherwise the object is stored as a literal. Claims with a literal object remain valid facts but do not become entity relationships.

## Relationships

A relationship is a canonical edge between two resolved entities, aggregated from claims.

- `entity_relationships`: `subject_entity_id`, `predicate`, `object_entity_id`, `support_count`, `provenance` (contributing claim and version references), unique per `(tenant_id, subject_entity_id, predicate, object_entity_id)`.

Relationships form only when both a claim's subject and object mentions resolve to entities. Each contributing claim is marked `linked` so re-runs do not double count.

## Normalization

Surface normalization is shared by mentions, aliases, and candidate generation:

```text
NFKC -> casefold -> punctuation to spaces -> collapse whitespace -> strip
```

The same surface always produces the same normalized key.

## Candidate Generation

Blocking is type-constrained and matches on:

- exact normalized name,
- exact alias form,
- `pg_trgm` trigram similarity above the trigram threshold on either.

Only active entities are considered. Blocking favors recall; scoring performs precise ranking.

## Scoring And Bands

Scoring is deterministic and pure. Features:

- name/alias similarity (dominant; max of token Jaccard and trigram similarity),
- type agreement,
- alias-exact,
- shared-document co-occurrence.

```text
score = 1.0 if alias-exact else name_similarity
score *= 0.4 if type mismatch
score += (1 - score) * 0.1 if shared document
```

Banded decision:

```text
score >= auto_threshold        -> auto-attach
review <= score < auto         -> review queue
score < review_threshold       -> new entity
```

Defaults: auto `0.85`, review `0.6`, trigram `0.3`. Thresholds are configurable via `ATLAS_ENTITY_RESOLUTION_*` settings.

## Merge Decisions

Every resolution outcome is recorded in `merge_decisions`:

- `decision_type`: `attach`, `merge`, `no_merge`, `split`.
- `source`: `auto` or `human`.
- `payload`: for merges, a full undo log (moved mentions, alias actions, per-relationship repoint/fold/self-loop actions) so a merge can be reversed by an `unmerge`.

`merge_candidates` records the scored candidate for auto attaches (status `applied`) and review-queue items (status `pending`, resolved to `accepted` or `rejected`).

## Serialization

Resolution runs one writer per tenant:

- a transaction-scoped PostgreSQL advisory lock guards the resolution transaction,
- a `ResolveEntitiesWorkflow` started via signal-with-start on workflow id `entity-resolution-{tenant}` ensures a single running resolution per tenant, draining pending mentions.

## Neo4j Projection

Neo4j holds `(:Entity {id, tenant_id, type, canonical_name, normalized_name, status})` nodes and `(:Entity)-[:RELATED {predicate, support, tenant_id}]->(:Entity)` edges. The projection:

- upserts active entities and relationships with `MERGE`,
- prunes nodes and edges no longer present in PostgreSQL (including merged-away entities),
- runs after the PostgreSQL transaction commits,
- is idempotent and rebuildable from PostgreSQL via `processes/graph_reconcile.py`.

## Current Limitations

- Relationship support can inflate across document re-ingests.
- Unmerge reverses the most recent merge and assumes no conflicting interleaved changes.
- Projection re-reconciles the whole tenant subgraph rather than applying deltas.
- The milestone stops before embeddings, vector indexes, and query-time orchestration.

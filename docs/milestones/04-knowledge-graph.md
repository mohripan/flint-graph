# Milestone 04: Knowledge graph and entity resolution

## Status

Complete. Phases 1 through 9 are implemented.

## Phase 1 Completed Behavior

Added Neo4j infrastructure and versioned graph migrations:

- Docker Compose includes a `neo4j` service (5.26 community) and a `neo4j-migrate` one-shot service.
- Settings expose `ATLAS_NEO4J_*` variables (URI, user, password, database, pool size, timeout).
- `atlas_rag.infrastructure.neo4j` defines a thin async `Neo4jClient` and driver factory.
- `atlas_rag.infrastructure.neo4j_migrations` runs versioned Cypher files from `migrations/neo4j/`, tracking applied versions as `(:_SchemaMigration)` nodes, and is idempotent.
- Migration `0001_entity_constraints` creates the `Entity.id` uniqueness constraint and a `(tenant_id, type, normalized_name)` lookup index.

## Phase 2 Completed Behavior

Added the PostgreSQL graph and entity-resolution schema:

- New enums for entity type, entity status, alias source, mention resolution status, claim status, relationship status, merge-candidate band/status, and merge-decision type/source.
- Seven tables: `canonical_entities`, `entity_aliases`, `entity_mentions`, `claims`, `entity_relationships`, `merge_candidates`, and `merge_decisions`.
- `canonical_entities` carries a self-referential `merged_into_id` for soft, reversible merges.
- The `pg_trgm` extension plus GIN trigram indexes on `canonical_entities.normalized_name` and `entity_aliases.normalized_form` back fuzzy candidate generation.
- Migration `0005_knowledge_graph` creates the tables, extension, and indexes.

## Phase 3 Completed Behavior

Extended structured extraction to a claims-aware schema:

- Extraction schema version is now `2` and the prompt version is `builtin-graph-v2`.
- Extraction emits relationship claims as `(subject, predicate, object)` triples with optional `evidence_chunk_ids`, alongside entities.
- Parsing is resilient: only non-JSON or non-object responses hard-fail. Malformed entities and claims are dropped individually while valid items are kept, and `summary` is optional. This lets small local models still produce usable graph facts.
- The prompt was hardened to steer models toward non-null string triple fields and exact key names.

## Phase 4 Completed Behavior

Persisted mentions and claims from extraction:

- `atlas_rag.application.entity_resolution.normalize_name` provides shared surface normalization (NFKC, casefold, punctuation and whitespace collapse).
- `persist_mentions_and_claims` derives `entity_mentions` (one per extracted entity, plus any claim subject not already present, typed `other`) and `claims` from a version's extraction facts.
- A claim object links to an entity mention when its surface matches one; otherwise it is stored as an `object_literal`.
- Mentions carry provenance: source extraction artifact id, prompt hash, response hash, and aggregated evidence chunk ids.
- Persistence is idempotent per document version and is wired into the ingestion pipeline activity after extraction.

## Phase 5 Completed Behavior

Added deterministic candidate generation and scoring:

- `atlas_rag.application.entity_resolution.scoring` provides pure similarity, feature, scoring, and banding functions with deterministic ordering.
- `generate_candidates` blocks candidate entities by exact normalized name, exact alias, or `pg_trgm` similarity, constrained to the mention's entity type and active entities only.
- Scoring combines name/alias similarity (dominant), type agreement, alias-exact, and shared-document co-occurrence into a `[0, 1]` score.
- Settings expose configurable auto, review, and trigram thresholds and a candidate limit.

## Phase 6 Completed Behavior

Implemented the resolution engine and banded decisions:

- `resolve_pending_mentions` applies banded outcomes per pending mention: auto-attach (score at or above the auto threshold), review queue (at or above the review threshold), or a new canonical entity (below review, or no candidate).
- Attaching registers an alias, maintains `support_count`, and records a reviewable merge decision. Auto attaches also record an applied merge candidate.
- `merge_entities` performs a soft, reversible entity-entity merge: `merged_into_id` pointer, re-parented aliases/mentions/relationships, folded duplicate edges, and dropped self-loops.
- `aggregate_relationships` folds resolved claims into `entity_relationships` with support counts and provenance, idempotently via claim status.
- Resolution is serialized per tenant with a PostgreSQL transaction-scoped advisory lock, driven by a `ResolveEntitiesWorkflow` started via signal-with-start on workflow id `entity-resolution-{tenant}`. The ingestion workflow enqueues resolution after a job completes.

## Phase 7 Completed Behavior

Projected the resolved graph into Neo4j:

- `load_tenant_graph` reads a tenant's active entities and relationships from PostgreSQL.
- `project_tenant_graph` reconciles the tenant's Neo4j subgraph with `MERGE` upserts plus pruning of stale nodes and edges, making it idempotent and drift-recoverable.
- Projection runs inside the resolution activity after the PostgreSQL transaction commits. A projection failure retries the activity and re-projects.
- `processes/graph_reconcile.py` rebuilds every tenant's graph from PostgreSQL for disaster recovery.

## Phase 8 Completed Behavior

Added the review and entity API:

- Tenant-scoped endpoints list and fetch canonical entities (with aliases, mentions, relationships), list the pending merge-review queue, submit a review decision, read the merge-decision audit log, and perform manual merge and unmerge.
- A review `accept` attaches the mention to the candidate entity; a `reject` creates a distinct new entity. Both re-aggregate claims.
- `unmerge_entity` reverses a merge using an undo log recorded in the merge decision payload (moved mentions, alias actions, and per-relationship repoint/fold/self-loop actions).
- Merge, unmerge, and review-decision endpoints project the affected tenant graph to Neo4j after committing.

## Phase 9 Completed Behavior

Completed documentation and manual verification:

- This milestone document, ADR `0004`, the knowledge-graph architecture contract, a developer runbook, and a semi-technical QA guide.
- README and AGENTS updated for the knowledge-graph milestone.
- Manual verification recorded in `notes/milestone-04/02-manual-testing-knowledge-graph.md`; a code-flow reading guide in `notes/milestone-04/03-code-flow-knowledge-graph.md`.

## Outcome Target

Milestone 04 turns per-document extraction output into a resolved, provenance-backed knowledge graph with reviewable, reversible merge decisions.

Target flow:

```text
document version activation
    -> extraction artifact (entities + claim triples, schema v2)
    -> entity mentions and raw claims persisted per version
    -> per-tenant serialized resolution
        -> candidate generation (deterministic + fuzzy)
        -> feature scoring and banded decision
        -> canonical entities, aliases, relationships
        -> reviewable, reversible merge decisions
    -> Neo4j projection (idempotent, rebuildable from PostgreSQL)
```

The milestone intentionally stops before embeddings, vector indexes, and query-time orchestration.

## Datastore Roles

- PostgreSQL is the system of record for entities, aliases, mentions, claims, relationships, merge candidates, and merge decisions.
- Neo4j is an idempotent, rebuildable projection of the resolved graph. It can always be reconstructed from PostgreSQL.
- MinIO continues to store immutable raw and derived artifacts, including extraction artifacts.

## Banded Resolution

```text
score >= auto_threshold    -> auto-attach mention to best entity
review <= score < auto     -> pending review queue (mention stays unresolved)
score < review_threshold   -> new canonical entity
no candidate               -> new canonical entity
```

Defaults: auto `0.85`, review `0.6`, trigram blocking `0.3`.

## Exit Criteria

- Neo4j is part of the local stack with a versioned Cypher migration runner.
- Extraction v2 emits claim triples with provenance; v1-style responses still parse.
- Mentions and claims are persisted per version with provenance, idempotently.
- Candidate generation and scoring are deterministic and unit-tested.
- Resolution runs serialized per tenant and applies banded decisions.
- Canonical entities, aliases, and relationships are correct and reversible.
- Every merge decision is recorded and reviewable; the review API works.
- Neo4j reflects the resolved graph and can be rebuilt from PostgreSQL.
- Tenant isolation holds across every new endpoint.
- Automated verification passes and live runs are recorded in the milestone notes.

## Known Limitations

- Re-ingesting a document version deletes and rebuilds its mentions and claims, but does not decrement prior relationship support contributions, so relationship `support_count` can inflate across re-ingests. A full recompute-from-claims would remove this.
- `unmerge_entity` reverses the most recent merge of an entity and assumes no conflicting graph changes occurred in between.
- Neo4j projection re-reconciles the whole tenant subgraph after each resolution; a delta-based projection is a future optimization for large tenants.
- Small local models produce noisy triples (reversed direction, literal objects). The pipeline faithfully persists what the model returns; triple quality is a model concern, not a pipeline defect.

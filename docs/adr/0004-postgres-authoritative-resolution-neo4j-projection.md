# ADR 0004: PostgreSQL-authoritative entity resolution with a Neo4j projection

## Status

Accepted.

## Context

Milestone 04 introduces a knowledge graph: canonical entities, aliases, mentions, claims, relationships, and human-reviewable, reversible merge decisions. The architecture vision uses Neo4j as the graph store, but entity resolution needs strong transactional guarantees, an auditable decision log, and the ability to reverse merges. A naive dual-write to two stores risks divergence when one write succeeds and the other fails.

## Decision

PostgreSQL is the system of record for the entire entity-resolution control plane and the resolved graph: `canonical_entities`, `entity_aliases`, `entity_mentions`, `claims`, `entity_relationships`, `merge_candidates`, and `merge_decisions`.

Neo4j is a projection of the resolved graph, not an independent source of truth. Every mutation commits to PostgreSQL first, then a projection step reconciles the tenant's Neo4j subgraph using idempotent `MERGE` upserts and prunes of stale nodes and edges.

Resolution is serialized per tenant with a transaction-scoped PostgreSQL advisory lock, so there is a single writer per tenant regardless of worker count. A `ResolveEntitiesWorkflow` is started via signal-with-start on workflow id `entity-resolution-{tenant}` so exactly one resolution runs per tenant at a time.

Merges are soft and reversible: the source keeps a `merged_into_id` pointer and status `merged`, and the merge decision records an undo log so an unmerge can restore the prior state.

## Consequences

- A committed PostgreSQL transaction is always the truth; a Neo4j projection failure is recoverable.
- The projection is idempotent and doubles as a rebuild: `processes/graph_reconcile.py` can reconstruct Neo4j entirely from PostgreSQL.
- Candidate generation, scoring, and projection stay simple because they operate only on active PostgreSQL rows; merge complexity is localized to the merge/unmerge services.
- The advisory lock removes concurrent-writer races without requiring distributed locking infrastructure.
- Every attach, merge, no-merge, and split is recorded in `merge_decisions` for audit and reversal.
- Neo4j and the API worker gain a hard dependency on PostgreSQL being authoritative; the graph is never written to directly by clients.

## Current Limitations

- Projection re-reconciles the whole tenant subgraph after each resolution rather than applying deltas.
- Relationship support counts can inflate across document re-ingests because clearing a version's claims does not decrement prior relationship contributions.
- Unmerge reverses the most recent merge and assumes no conflicting interleaved graph changes.
- Neo4j multi-tenancy is enforced by a `tenant_id` property on every node and relationship, not by separate databases.

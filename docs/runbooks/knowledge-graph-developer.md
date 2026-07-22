# Knowledge Graph Developer Runbook

## Purpose

Use this runbook when changing or debugging the resolved knowledge graph: entity resolution, candidate generation, scoring, banded decisions, merges, relationship aggregation, and the Neo4j projection. Milestone 05 feeds this graph from staged extraction proposals rather than the original Milestone 04 mention/claim bridge.

For semi-technical manual validation, use `docs/runbooks/knowledge-graph-qa-guide.md`.

## Local Stack

Start the complete stack:

```powershell
docker compose up --build
```

Reset local state (drops PostgreSQL, MinIO, Neo4j, and observability volumes):

```powershell
docker compose down -v
```

Useful pages and logs:

```powershell
docker compose logs -f ingestion-worker
docker compose logs -f api
```

- Neo4j browser: `http://localhost:7474` (user `neo4j`, password `flintgraphpassword`)
- Temporal Web UI: `http://localhost:8233`

## Resolution Path

```text
document version activation
    -> provenance extraction run and staged proposals
    -> proposal candidate generation
    -> ingestion workflow enqueues ResolveEntitiesWorkflow (signal-with-start, id entity-resolution-{tenant})
    -> resolve_tenant_entities activity
        -> pg advisory lock (single writer per tenant)
        -> staged resolver: auto attach / review / new entity
        -> aggregate relationships from resolved staged relations and entity-object claims
        -> commit PostgreSQL
    -> project_tenant_graph (Neo4j MERGE + prune)
```

Review, manual merge, and unmerge happen through the API and also project to Neo4j after committing.

## Configuration

```env
FLINT_GRAPH_NEO4J_URI=bolt://neo4j:7687
FLINT_GRAPH_NEO4J_USER=neo4j
FLINT_GRAPH_NEO4J_PASSWORD=flintgraphpassword
FLINT_GRAPH_NEO4J_DATABASE=neo4j
FLINT_GRAPH_ENTITY_RESOLUTION_AUTO_THRESHOLD=0.85
FLINT_GRAPH_ENTITY_RESOLUTION_REVIEW_THRESHOLD=0.6
FLINT_GRAPH_ENTITY_RESOLUTION_TRIGRAM_THRESHOLD=0.3
FLINT_GRAPH_ENTITY_RESOLUTION_CANDIDATE_LIMIT=20
```

Extraction defaults to `gemma3:1b` through Ollama. Small local models can produce sparse proposals; failed or rejected extraction output is recorded in provenance tables and does not directly mutate the canonical graph.

## Database Checks

Entities and support counts:

```powershell
docker compose exec postgres psql -U flint_graph -d flint_graph -c "select canonical_name, entity_type, status, support_count from canonical_entities order by support_count desc, canonical_name limit 20;"
```

Staged entities and resolution status:

```powershell
docker compose exec postgres psql -U flint_graph -d flint_graph -c "select name, entity_type, resolution_status, resolved_canonical_entity_id from extracted_entities order by created_at desc limit 20;"
```

Relationships:

```powershell
docker compose exec postgres psql -U flint_graph -d flint_graph -c "select subject_entity_id, predicate, object_entity_id, support_count from entity_relationships order by support_count desc limit 20;"
```

Merge decision audit:

```powershell
docker compose exec postgres psql -U flint_graph -d flint_graph -c "select decision_type, source, actor, reason, created_at from merge_decisions order by created_at desc limit 20;"
```

## Neo4j Checks

```cypher
MATCH (e:Entity) RETURN e.tenant_id, e.type, e.canonical_name, e.status ORDER BY e.canonical_name;
MATCH (s:Entity)-[r:RELATED]->(o:Entity) RETURN s.canonical_name, r.predicate, o.canonical_name, r.support;
```

The Neo4j graph must match active PostgreSQL rows for a tenant. If it drifts, rebuild it:

```powershell
docker compose run --rm ingestion-worker python -m flint_graph.processes.graph_reconcile
```

## Opt-In Integration Tests

Some tests require live infrastructure and are skipped by default:

```powershell
# Neo4j (migration runner + projection)
$env:FLINT_GRAPH_NEO4J_INTEGRATION = "1"
uv run pytest tests/integration/test_neo4j_migrations_integration.py tests/integration/test_graph_projection_neo4j.py

# PostgreSQL pg_trgm candidate generation
$env:FLINT_GRAPH_PG_INTEGRATION = "1"
uv run pytest tests/integration/test_candidate_generation.py
```

## Failure Modes

- Extraction returns non-JSON: recorded as a failed extraction; no mentions are created; the job still completes in optional mode.
- Two documents mention the same entity: the second mention auto-attaches to the first document's entity and `support_count` increases.
- Mid-band candidate: the mention goes to the review queue and stays unresolved until a human decides.
- Projection failure: the resolution activity retries and re-projects idempotently; PostgreSQL is unaffected.

## Verification Commands

Run before ending behavior-changing work:

```powershell
uv run pytest
uv run ruff check .
uv run mypy
uv run alembic upgrade head --sql
docker compose config
```

For phases touching resolution or projection, also run at least one real Docker Compose ingestion smoke test and record results in `notes/milestone-04/02-manual-testing-knowledge-graph.md`.

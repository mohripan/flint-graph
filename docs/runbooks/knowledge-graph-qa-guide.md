# Knowledge Graph QA Guide

## Status

Milestone 04 is complete. After a document is ingested, FlintGraph resolves the extracted entities into canonical entities, aggregates relationships, records reviewable merge decisions, and projects the resolved graph into Neo4j.

## Audience

This guide is for QA, project managers, and other semi-technical users who can run Docker and PowerShell commands. It shows what to do, what should happen, which tables change, and how to see the graph in Neo4j.

## Local Services

Start the application:

```powershell
docker compose up --build
```

Useful pages:

- API docs: `http://localhost:8000/docs`
- Neo4j browser: `http://localhost:7474` (user `neo4j`, password `flintgraphpassword`)
- Temporal Web UI: `http://localhost:8233`
- MinIO console: `http://localhost:9001`

For clearer entity extraction, run Ollama with a stronger local model and point the worker at it:

```env
FLINT_GRAPH_OLLAMA_MODEL=llama3.2:latest
```

## Step 1: Create A Tenant

```powershell
$tenant = curl.exe -sS -X POST http://localhost:8000/v1/tenants `
  -H "Content-Type: application/json" `
  -d '{"name":"QA Knowledge Graph"}' | ConvertFrom-Json

$tenant.id
```

## Step 2: Ingest Two Related Documents

Create two files that mention the same entities:

```powershell
@"
# Acme Corporation

Acme Corporation is a technology company headquartered in Berlin.
Jane Doe founded Acme Corporation.
"@ | Set-Content -Encoding utf8 .\acme1.md

@"
# Acme News

Berlin remains the headquarters of Acme Corporation, and Jane Doe leads the company.
"@ | Set-Content -Encoding utf8 .\acme2.md
```

Upload both:

```powershell
curl.exe -sS -X POST http://localhost:8000/v1/documents/uploads `
  -H "X-Tenant-ID: $($tenant.id)" -H "Idempotency-Key: qa-acme-1" `
  -F "title=Acme 1" -F "external_id=qa-acme-1" -F "file=@acme1.md;type=text/markdown"

curl.exe -sS -X POST http://localhost:8000/v1/documents/uploads `
  -H "X-Tenant-ID: $($tenant.id)" -H "Idempotency-Key: qa-acme-2" `
  -F "title=Acme 2" -F "external_id=qa-acme-2" -F "file=@acme2.md;type=text/markdown"
```

What should happen:

- Each upload creates a durable ingestion job that reaches `completed`.
- After each job completes, per-tenant resolution runs and creates or updates canonical entities.

## Step 3: See The Resolved Entities

```powershell
curl.exe -sS "http://localhost:8000/v1/entities" -H "X-Tenant-ID: $($tenant.id)" | ConvertFrom-Json
```

What to expect:

- An entity such as "Acme Corporation" mentioned in both documents appears once with `support_count` of 2.
- Entities only in one document have `support_count` of 1.

Database check:

```powershell
docker compose exec postgres psql -U flint_graph -d flint_graph -c "select canonical_name, entity_type, support_count from canonical_entities order by support_count desc;"
```

## Step 4: Inspect An Entity

```powershell
curl.exe -sS "http://localhost:8000/v1/entities/<entity-id>" -H "X-Tenant-ID: $($tenant.id)" | ConvertFrom-Json
```

The response includes the entity's aliases, its mentions across documents, and its relationships.

## Step 5: See The Graph In Neo4j

Open `http://localhost:7474`, log in, and run:

```cypher
MATCH (s:Entity)-[r:RELATED]->(o:Entity)
RETURN s.canonical_name, r.predicate, o.canonical_name, r.support;
```

What this proves:

- The resolved PostgreSQL graph is projected into Neo4j.
- Nodes are canonical entities; edges are relationships aggregated from claims.

## Step 6: Review Queue

Ambiguous matches go to a review queue instead of auto-merging.

```powershell
curl.exe -sS "http://localhost:8000/v1/merge-reviews" -H "X-Tenant-ID: $($tenant.id)" | ConvertFrom-Json
```

If an item is present, accept or reject it:

```powershell
curl.exe -sS -X POST "http://localhost:8000/v1/merge-reviews/<candidate-id>/decision" `
  -H "X-Tenant-ID: $($tenant.id)" -H "Content-Type: application/json" `
  -d '{"decision":"accept","reason":"same company"}'
```

- Accept attaches the mention to the candidate entity.
- Reject creates a new distinct entity for the mention.

## Step 7: Manual Merge And Unmerge

Merge one entity into another:

```powershell
curl.exe -sS -X POST "http://localhost:8000/v1/entities/<source-id>/merge" `
  -H "X-Tenant-ID: $($tenant.id)" -H "Content-Type: application/json" `
  -d '{"target_entity_id":"<target-id>","reason":"duplicate"}'
```

Expected:

- The source entity's detail shows `status` `merged` and `merged_into_id` set.
- The Neo4j node count drops by one (the merged node is pruned).

Reverse it:

```powershell
curl.exe -sS -X POST "http://localhost:8000/v1/entities/<source-id>/unmerge" `
  -H "X-Tenant-ID: $($tenant.id)" -H "Content-Type: application/json" `
  -d '{"reason":"was not a duplicate"}'
```

Expected:

- The source entity is `active` again with `merged_into_id` cleared.
- The Neo4j node is restored.

## Step 8: Audit Log

```powershell
curl.exe -sS "http://localhost:8000/v1/merge-decisions" -H "X-Tenant-ID: $($tenant.id)" | ConvertFrom-Json
```

Every attach, merge, and split (unmerge) is recorded with its source (`auto` or `human`), actor, and reason.

## Note On Model Quality

Small local models produce noisy triples (reversed direction, vague or literal objects). FlintGraph faithfully persists what the model returns; triple quality improves with a stronger extraction model. Entity resolution and merge review operate correctly regardless.

## Clean Reset

```powershell
docker compose down -v
```

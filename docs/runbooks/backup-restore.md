# Backup And Restore Runbook

PostgreSQL is authoritative for FlintGraph control-plane and retrieval state.
MinIO contains immutable raw and derived artifacts that must be restored with
the matching PostgreSQL backup. Neo4j and OpenSearch are rebuildable
projections.

## Backup Order

1. Pause API writes or enter a maintenance window.
2. Back up PostgreSQL with a consistent snapshot.
3. Back up MinIO buckets for raw and derived artifacts.
4. Preserve the application version, migration revision, `.env` configuration,
   and model/index settings used by the snapshot.
5. Optionally archive `evals/` reports and baselines with the release artifact.

Neo4j and OpenSearch backups are optional for faster recovery, but they are not
the authoritative source.

## Restore Order

1. Restore PostgreSQL.
2. Restore MinIO artifacts.
3. Run PostgreSQL migrations to the application version:

   ```powershell
   uv run alembic upgrade head
   ```

4. Run Neo4j migrations.
5. Reconcile or rebuild projections:

   ```powershell
   python -m flint_graph.processes.retrieval_index_reconcile
   python -m flint_graph.processes.document_projection_cleanup
   ```

6. Start the outbox relay and ingestion worker.
7. Run a workspace readiness check and start an active-index backfill if
   coverage is missing or stale.

## Post-Restore Smoke

For one restored workspace:

1. `GET /v1/system-readiness`
2. `GET /v1/search-readiness`
3. `GET /v1/documents`
4. `POST /v1/search/lexical`
5. `POST /v1/search/vector`
6. Create and stream one query run.
7. Verify answer provenance and citation provenance.

If Neo4j or OpenSearch projections are empty but PostgreSQL coverage exists,
run the retrieval reconcile process and then poll search readiness again.


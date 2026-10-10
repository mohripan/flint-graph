# Evidence identity and extraction retries: 2026-10-10

Tracking: [#55](https://github.com/mohripan/flint-graph/issues/55).

Tests first reproduced tenant-unique evidence collisions between different
documents/versions, SQL flush failure followed by `PendingRollbackError`, and
failed-to-ready retry rejection by the extraction-run unique key. Fixed with
version-scoped `ev_v2_` IDs, savepoint-protected proposal persistence, reuse of the
failed contract run and appended invocation history. Ready provenance is not
downgraded by later provider failures. Existing IDs/manifests are not migrated.

Passed checks:

- `uv run pytest -q`: 624 passed, 6 skipped.
- `FLINT_GRAPH_PG_INTEGRATION=1 uv run pytest tests/integration/test_provenance_extraction_persistence.py tests/integration/test_ingestion_activities.py tests/unit/test_extraction_evidence.py -q`: 25 passed, including four PostgreSQL cases.
- `uv run ruff check .` (initial three line-length errors corrected and rerun),
  `uv run mypy` (149 files), `uv lock --check`.
- Unchanged deterministic evaluation/baseline gate, offline Alembic SQL with
  deterministic providers, `docker compose config --quiet`, `git diff --check`.

PostgreSQL tests use generated isolated schemas and remove only those schemas;
public tables, real workspaces and Docker volumes are untouched.

## Live retry and remaining projection verification

Rebuilt only the ingestion worker, preserving its explicit deterministic
extraction/embedding configuration and leaving other services/volumes intact.
Re-ran the 100-document public-API preparation:

```powershell
uv run flint-graph-eval prepare --dataset notes/finqa-batch-0 --base-url http://localhost:8000 --output notes/finqa-batch-0-live-manifest.json --prepare-timeout 900
```

New workspace: `2eab2f78-208e-4eb9-97a2-087e40af0525`.
Active index: `fc8aa4e9-6b7f-4283-99cf-efc850a472e1`.
Public API checks found all 100 immutable document versions active and all 100
index coverage rows completed, none failed. The original failed workspace
`ff05efae-e8ae-4577-8801-7af5e3a29e35` was preserved.

Preparation repeatedly returned empty narrow-document vector searches because
ANN candidates are selected globally before filters. That separate retrieval
bug is [#56](https://github.com/mohripan/flint-graph/issues/56). Verified helper
PIDs 3960/9396 were stopped; no ingestion service or data was stopped/deleted.
At that point, no successful preparation manifest or financial model-quality
result was claimed. Follow-up #56 passed both projection probes for all 100
versions twice without uploads; see the [verification report](2026-10-10-scoped-vector-delivery.md).
Financial answer quality is still a separate #53 task.

No frontend/browser changes, paid provider calls, embedding model downloads,
cross-contract re-extraction coordination or large-corpus scale claims.
Decision: [ADR 0017](../adr/0017-version-scoped-evidence-and-extraction-retries.md).

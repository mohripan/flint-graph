# Narrow-vector scope and financial preparation verification: 2026-10-10

Tracking: [#56](https://github.com/mohripan/flint-graph/issues/56), completing
live preparation checks for #54/#55.

Explicit document/version/chunk scopes now select tenant/index-filtered Neo4j
nodes before exact cosine scoring, bounded to 5,000 candidates. A 5,001-node
sentinel rejects oversized scopes with 409 before scoring, not truncated hits.
Unscoped tenant queries still use ANN; providers/models/indexes do not change.
Score semantics follow [Neo4j's vector function](https://neo4j.com/docs/cypher-manual/current/functions/vector/).

Added explicit existing-workspace/index CLI UUIDs and `--verify-only`. That mode
performs no uploads/bootstrap/deletes and requires unique active document labels,
per-version positive completed coverage, both projections and an unchanged index.
Its local source hashes are not independent API source-byte attestation.
Ordinary preparation retains explicit upload behavior.

## Actual native-service checks

Rebuilt only the API, preserving local Gemma answer/support models and deterministic
384-dimensional embeddings. Other services/volumes were preserved.

```powershell
uv run flint-graph-eval prepare --dataset notes/finqa-batch-0 --base-url http://localhost:8000 --workspace-id 2eab2f78-208e-4eb9-97a2-087e40af0525 --index-version-id fc8aa4e9-6b7f-4283-99cf-efc850a472e1 --verify-only --output notes/finqa-batch-0-verified-manifest.json --prepare-timeout 300
```

Passed: all 100 active versions/coverage rows, 100 lexical and 100 vector positive
probes against actual services. The manifest remains gitignored. Repeated
verification used a new output and the same existing document/version identities;
no corpus reupload or new workspace/index was needed. Foreign-version probes
from another workspace and absent-version probes each returned zero vector hits.
The original failed workspace remains inspectable.

## Gates and limits

Tests preceded behavior: three narrow filter cases, oversized-scope rejection,
paired UUID validation and four verify-only success/failure cases. Focused tests:
35 passed. Full `uv run pytest -q`: 633 passed, 6 skipped. Ruff, mypy (149 files),
`uv lock --check`, unchanged deterministic eval/baseline gate, offline Alembic SQL
with deterministic providers, Compose config and diff checks passed. No data
migration was executed.

No frontend/browser changes, paid inference or model downloads. The 5,001-candidate
rejection is contract-tested, not a live 5,001-node load test. Deterministic
embeddings prove projection visibility, **not semantic financial quality**.
Unscoped selective-tenant ANN recall, native pgvector/pgvectorscale, latency under
load and large-corpus benchmarks remain open work.

# Complete search-readiness totals — 2026-10-10

Live UI QA found [#66](https://github.com/mohripan/flint-graph/issues/66): readiness
counted only 25 recent preview rows. Older searchable documents could disappear
from query eligibility when enough newer versions were still pending. Many
versions of one document could also consume the preview limit before application
deduplication. Completed coverage incorrectly counted pending/failed/cancelled
source versions that retrieval would not serve.

HTTP regressions were added first and reproduced five failures. Readiness now
groups the complete tenant/active-index PostgreSQL ledger, counts completed
coverage only on active source versions, excludes foreign/deleted/superseded
sources and other indexes, and ranks preview versions per document in SQL before
limiting. Older active content remains available despite newer failed attempts.
The response shape and 25-document preview bound are unchanged. This is a
correctness fix, not a large-corpus query-plan or ANN performance qualification.

PostgreSQL-enabled readiness/query tests passed 22 cases, covering older content
beyond 30 newer pending documents and successful query creation, 30 failed
attempts without starving the preview, all five nonactive source statuses,
full coverage totals (30 completed / 7 running / 4 failed / 2 cancelled), foreign
tenants, logically deleted documents and wrong indexes. Current active-index
selection/tenant authorization are retained.

The API was rebuilt with inspected/validated local Ollama answer/support settings
preserved. Real GET readiness on the existing public financial workspace
`2eab2f78-208e-4eb9-97a2-087e40af0525` reports ready, 100 completed versions and 25
preview rows; an isolated real-browser check verified the visible 100-version
badge. The user's workspace reports ready, one completed version, zero running
and zero failed coverage. Only aggregate metadata was read there; no private
contents or question were sent to a model or shared evaluation. No synthetic
documents or new queries were created in the live service by this slice.

Passed: `uv run pytest -q` (675 passed, 6 optional integration skips), focused
PostgreSQL-enabled readiness tests (22 passed), `uv run ruff check .`, `uv run
mypy` (151 files), `uv lock --check`, the exact AGENTS.md deterministic acme-smoke
evaluation, `FLINT_GRAPH_ENV=test uv run alembic upgrade head --sql` (1,026 lines),
`docker compose config --quiet`, `git diff --check`, and the real browser badge
check above. Frontend source was unchanged; its test/typecheck/build/full browser
gates passed in the preceding #65 slice and were not rerun here. Model-quality,
projection delay/load benchmarks and OIDC live login were not exercised.
Frontend remains available at `http://127.0.0.1:5173`.

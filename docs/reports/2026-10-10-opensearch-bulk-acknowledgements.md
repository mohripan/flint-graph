# OpenSearch bulk acknowledgement verification

Tracking: [issue #68](https://github.com/mohripan/flint-graph/issues/68), prerequisite
for [partial-projection cleanup #67](https://github.com/mohripan/flint-graph/issues/67).

The adapter previously accepted every HTTP-success bulk response. Tests first
reproduced 20 incorrectly accepted cases. It now validates all submitted actions,
response count/order, strict status types, per-item errors and aggregate errors.
Invalid JSON and bulk HTTP failures also use bounded, redacted exception messages.
Already-missing deletes remain retry-safe; other 404 operations fail. Empty batches
perform no HTTP request. No implicit or unbounded retry was introduced.

The response contract follows the official
[OpenSearch Bulk API](https://docs.opensearch.org/latest/api-reference/document-apis/bulk/).
HTTP-success responses can describe partial failure, and a successful missing
delete returns `not_found` with status 404.

## Live verification

A UUID-named disposable `flintgraph-bulk-verification-...` index with an integer
mapping received one valid and one invalid synthetic record. The adapter rejected
the partial failure, the valid record existed and the invalid record did not.
The exception contained neither the synthetic private-text marker nor the index
identifier. A mixed existing/missing delete and a repeated delete both succeeded.
Only that disposable synthetic index was then removed. No project index, user
document, raw object or model was touched. This does not prove full lifecycle
cleanup; issue #67 remains separate.

## Verification

- `uv run pytest tests/unit/test_opensearch_projection.py -q`: 35 passed.
- PostgreSQL lifecycle suite: 30 passed, 2 SQLite-only skips.
- Ruff, mypy (151 source files), lock consistency, deterministic evaluation gate,
  Alembic offline SQL (1,026 lines), Compose configuration and diff checks passed.
- `uv run pytest -q`: 713 passed, 8 conditional skips (including the two
  PostgreSQL-only concurrency cases skipped in the offline SQLite run).
- Frontend gates skipped: no frontend changes; the previously verified UI remains
  running at `http://127.0.0.1:5173`.

Limitations: successful items may persist before a later item fails. The adapter
does not roll them back, selectively retry them or provide atomic bulk semantics.

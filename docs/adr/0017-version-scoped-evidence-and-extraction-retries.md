# ADR 0017: version-scoped evidence and recoverable extraction persistence

Status: accepted. Date: 2026-10-10.
Tracking: [#55](https://github.com/mohripan/flint-graph/issues/55).

The first 100-excerpt financial corpus ingestion failed because identical
boilerplate in distinct documents produced the same tenant-unique evidence ID.
Chunk IDs and offsets are document-local; they cannot identify tenant-wide rows.

New verified spans use `ev_v2_` plus the SHA-256 of a canonical JSON array:
immutable document-version UUID, chunk ID, exact start/end offsets and quote hash.
Document-version UUIDs already identify globally distinct records. Require the
version UUID at the pure resolver boundary. Identical evidence within one version
still deduplicates; other documents/new immutable versions receive distinct IDs.
Staged proposal IDs inherit the evidence scope. Keep current unique constraints.
Existing IDs, links, immutable manifests and ready runs remain untouched: no data
migration rewrites historical provenance. Same-contract retries reuse ready runs.

Wrap proposal persistence in a database savepoint, retaining already-materialized
content artifacts outside it. Failed SQL flushes roll back staged rows before a
failed invocation is recorded. This follows SQLAlchemy's documented
[savepoint transaction boundary](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html#using-savepoint).
Object-store writes are immutable and not rolled back by SQL; unreferenced derived
artifacts may remain after a failed attempt and are not deleted automatically.

A failed extraction-contract run may become ready after a successful retry.
Reuse its unique run row, append invocation indexes/counts, and preserve earlier
failed invocation diagnostics. Later provider failures append a failed invocation
without downgrading existing ready provenance. Optional extraction can continue
after a safely recorded failure; required extraction still raises and is recorded
by the worker's existing commit/failure path. No failure is relabeled success.

This does not implement concurrent re-extraction coordination or migration between
different model/prompt contracts over the same already-extracted immutable version.
Those need explicit staged-record/evidence reuse semantics, not weakened uniqueness.

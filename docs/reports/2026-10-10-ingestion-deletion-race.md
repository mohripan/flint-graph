# Ingestion deletion-race delivery — 2026-10-10

[#58](https://github.com/mohripan/flint-graph/issues/58) was found when a private
document was deleted during ingestion: Temporal failed but PostgreSQL still said
running because failure reporting attempted a deleted-to-failed version change.
The original private source/job was not restored, replayed, reuploaded or repaired
by this verification. Its historical state is left for explicit operator action.

Tests first reproduced queued/running jobs left nonterminal after deletion and
source reads after deletion. Deletion now writes cancellation/events/outbox
atomically; repeated cancellation is dispatch-idempotent. Late deleted-job
callbacks are ignored or settle a legacy nonterminal job without version
reactivation. Authorized document-first locks and fresh row reads serialize job,
version, content and indexing mutations with deletion. Source/persistence guards
refuse deleted/cancelled/superseded content before new pipeline output.

Live checks caught a configuration gap in the first tests: refreshing ORM rows
under runtime `autoflush=False` discarded pending tombstones. New regressions
reproduced four failures under that exact configuration. Explicit flush under
the existing document lock fixes it; both flushing modes are now covered. Initial
synthetic attempts remain isolated test records, not passed verification. No
private-user material was involved. Final full and live checks below passed.

Final isolated live workspace: `a1f122fd-bc3f-48a8-8aee-6114c14b9cad`. Two synthetic
approximately 1.1 MB uploads were deleted, one observed queued and one observed
running. API deletion took 32 ms and 16 ms respectively in this tiny local smoke,
not a concurrency/capacity SLA. Both jobs and Temporal workflows ended cancelled.
Two repeated API cancellations per job still produced one cancellation event.
Read-only PostgreSQL inspection confirmed one published cancellation dispatch per
job, deleted versions/documents and zero chunk rows. Readiness is false and the
document list retains two tombstones as intended. Raw objects remain retained;
logical deletion is not source erasure. No model-quality calls were made.

Existing local models, embeddings, services and volumes were preserved while
rebuilding API/worker; API answer/support Ollama settings were verified. Frontend
remains at `http://127.0.0.1:5173`. There is no instant-deletion guarantee: current
content/model/index transactions hold the document lock and can delay deletion.
Physical cleanup of incomplete projections is tracked separately in #67.

Final verification: `uv run pytest -q` passed 685 tests with 8 skips (6 optional
external integration checks plus 2 PostgreSQL-only lock tests in the default
SQLite run). PostgreSQL-enabled focused lifecycle tests passed 18 with 2 expected
SQLite-only lock skips, including both autoflush modes and the real stale-session
race. The broader ingestion/content/job/retrieval suite also passed before the
final explicit-flush correction (67 passed, 2 skips); it is not substituted for
the final lifecycle regression. `uv run ruff check .`, `uv run mypy` (151 files),
`uv lock --check`, exact AGENTS.md deterministic acme-smoke evaluation,
`FLINT_GRAPH_ENV=test uv run alembic upgrade head --sql` (1,026 lines),
`docker compose config --quiet`, and `git diff --check` passed. Frontend code was
unchanged; #65 frontend gates were not rerun. Long model-transaction latency,
physical partial-projection cleanup and private-source ingestion were not proven.

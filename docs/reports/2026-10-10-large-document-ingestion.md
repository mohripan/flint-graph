# Large-document optional extraction delivery — 2026-10-10

[#61](https://github.com/mohripan/flint-graph/issues/61) followed the NUL parser
fix. A single extraction request accepts at most 100 chunks. Previously its
validation ran outside the optional-extraction failure boundary, preventing a
large document from reaching retrieval indexing.

The worker now checks the shared bound before invoking the provider, persists a
failed extraction run with `extraction_input_limit_exceeded`, and continues
optional ingestion with **all** chunks. Required extraction still fails visibly.
The recorded request hash covers the complete intended input; neither truncation
nor a provider call occurs. The fixed error message does not expose chunk text.
This is retrieval availability, not full-document graph extraction; bounded
multi-batch graph extraction is tracked in
[#64](https://github.com/mohripan/flint-graph/issues/64).

Tests were added before implementation for optional and required modes, using
120 chunks and both SQLite and PostgreSQL. They inspect persisted chunks, failed
extraction provenance and zero provider requests. Seventeen focused ingestion
cases passed with `FLINT_GRAPH_PG_INTEGRATION=1`.

Only the ingestion worker was rebuilt, preserving its deterministic extraction
and embedding configuration and existing data. A new isolated public-API smoke
uploaded a synthetic approximately 1.18 MB text document: all 1,085 chunks were
embedded and projected, the job completed, the version became active, coverage
completed and readiness became true. Positive lexical and vector probes passed.
PostgreSQL inspection confirmed the bounded extraction failure above. Workspace
`920ebbfc-6dff-4df6-8881-7b301efd2dab`, index
`7f73cfc8-718e-419d-8412-8654f45af51b`. No private document was restored, reuploaded
or included in shared evaluation data.

Verification passed: `uv run pytest -q` (666 passed, 6 optional integration
skips), `uv run ruff check .`, `uv run mypy` (151 files), `uv lock --check`, the
exact AGENTS.md deterministic acme-smoke evaluation, `FLINT_GRAPH_ENV=test uv run
alembic upgrade head --sql` (1,026 lines), `docker compose config --quiet`, and
`git diff --check`. Live smoke uses fixture embeddings, not qualified real-model
retrieval or book/formula/OCR quality. Full large-document graph extraction and
deleted private-source ingestion were not performed. Frontend remains available
at `http://127.0.0.1:5173`.

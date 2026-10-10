# NUL-safe parser delivery — 2026-10-10

[#57](https://github.com/mohripan/flint-graph/issues/57) was found while diagnosing
a user-uploaded Discrete Math document with zero readiness. The original Temporal
activity failed with PostgreSQL `CharacterNotInRepertoireError`, UTF8 byte 0x00.
The user had deleted the document while ingestion was running. A second failure
attempted to change the deleted version to failed; #58 tracks that lifecycle race.
Neither deletion was performed by this work, nor was the deleted file restored.

Parser public regressions first reproduced NUL for text/Markdown/HTML/PDF.
Normalization now replaces NUL with U+FFFD and records a count warning. Raw
content hashes/bytes are untouched. SQLite and PostgreSQL artifact persistence
and normalized exact-evidence offsets are verified. See the content contract.

The retained raw Discrete Math object was read without writing, copying, indexing,
restoring or querying its contents with a model. Configured bounded parser:
2,599,495 raw bytes, matching original SHA-256, 540 elements, 1,085 chunks,
450 parsed-text replacements, zero NUL in normalized/chunk text. Only aggregate
counts were logged; no document contents were committed or sent to GitHub.
No claim of full ingestion or model quality for this deleted document.

The rebuilt worker preserved deterministic extraction/embedding settings and
existing services/volumes. A separate synthetic two-file public-API upload used
NUL-containing plain text and a text PDF. Both jobs completed, both versions
became active, both coverage rows completed, readiness became true, and positive
lexical/vector projection probes passed. Workspace:
`fa7fd3f9-c840-4a3a-9122-89faea8b613f`; active index:
`0f165a3e-2f34-4b60-8776-eabf008edf37`. This is fixture embedding verification.

Read-only inspection also identified #61: 1,085 chunks exceed the current
single-request extraction bound of 100. That must be addressed before claiming
this large book can complete ingestion. OCR/layout/math-formula fidelity remains
unqualified. No private material is in the public financial nightly suite.

Verification: parser/artifact tests with `FLINT_GRAPH_PG_INTEGRATION=1` passed
23 cases (SQLite and PostgreSQL persistence), extraction evidence tests passed
7 cases. Final `uv run pytest -q` passed 664 cases with 6 optional external-
integration skips. `uv run ruff check .`, `uv run mypy` (151 files),
`uv lock --check`, the exact AGENTS.md deterministic acme-smoke eval,
`FLINT_GRAPH_ENV=test uv run alembic upgrade head --sql` (1,026 lines),
`docker compose config --quiet`, and `git diff --check` passed. OCR, model quality
on this private book and full real-model embedding paths were skipped/unqualified.
Frontend remains at 127.0.0.1:5173.

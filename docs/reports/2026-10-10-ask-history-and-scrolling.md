# Ask history and scrolling delivery — 2026-10-10

[#65](https://github.com/mohripan/flint-graph/issues/65) addresses the user's
screenshot: a flex-shrunk, overflow-hidden result grid left a tiny nested answer
pane beneath always-expanded diagnostics. The result now grows naturally inside
one primary page scroll. Answers precede collapsed diagnostics; sources retain
their natural height. Long unbroken text and source titles cannot widen the page.

The design retains existing Inter/system sans for headings/body, monospace
citation identifiers, white paper (`#ffffff`), slate canvas (`#f8fafc`), ink
(`#0f172a`), muted slate (`#64748b`), brand indigo (`#4f46e5`) and evidence green
(`#059669`). The subject is document research, the audience workspace readers,
and the page's job is reading grounded answers with evidence. The distinguishing
interaction is an expandable, dated saved-question ledger that reopens evidence,
not a horizontal carousel that merely copies prompts. A permanent chat sidebar
was rejected here because it crowds the existing source column/composer; a new
font, color system or decorative animation would not help this layout repair.

Question history searches authorized stored questions and loads older pages with
a stable timestamp/UUID cursor. Selecting a run uses GET for its saved answer
and provenance, with no query creation or model invocation. Completed, abstained,
failed, cancelled and pending outcomes remain distinct. Explicit New question
clears the result. The UI discloses that questions are independent; true chained
conversations remain #62. No conversational state or durable background execution
is claimed. Polling search readiness no longer downloads full history every five
seconds. History refresh is explicit and also occurs after a new run finishes.

Workspace-keyed page lifetimes and abort/response guards clear previous answers
immediately and reject late responses from old requests. The backend history
cursor resolves under the same tenant authorization; foreign/unknown cursors
return 404, literal search escapes SQL wildcards, and new insertions do not shift
older pages. No migration or changed list-response shape is required. Substring
search is not an indexed full-text search or a measured high-volume benchmark.

Tests were added before implementation. The HTTP regression failed because the
old endpoint ignored search; SQLite and PostgreSQL now verify literal search,
timestamp ties, pagination, inserts, tenant isolation and validation. Browser
fixtures cover 60 answer paragraphs, 24 citations, long unbroken titles/text,
390px/1280px widths, reaching the final citation, diagnostics toggle, no POST on
reopen, cursor pagination, search/empty results, failed/abstained/pending results,
and an intentionally delayed response across a workspace switch. The browser
test uses a separate session and synthetic HTTP fixtures, not private content.

Live verification used the running Vite frontend/API and the previously captured
public financial corpus: selected a workspace, reopened its saved forecast answer
with one source, checked both desktop and mobile screenshots and collapsed
diagnostics, and traversed two two-row history pages with zero duplicates. No
model call or user document mutation was needed. Only the API was rebuilt; its
installed Ollama answer/support settings were restored and verified after a
Compose invocation initially reapplied offline defaults. Existing embeddings,
services and data were preserved. Frontend remains at `http://127.0.0.1:5173`.

Verification passed: `uv run pytest -q` (667 passed, 6 optional integration skips),
PostgreSQL-enabled query API/ledger tests (50 passed, 3 conditional skips),
`uv run ruff check .`, `uv run mypy` (151 files), `uv lock --check`, the exact
AGENTS.md deterministic acme-smoke evaluation, `FLINT_GRAPH_ENV=test uv run
alembic upgrade head --sql` (1,026 lines), `docker compose config --quiet`,
`git diff --check`, and frontend `npm test` (8 passed), `npm run typecheck`,
`npm run build`, `npm run test:browser`. Chained model quality, durable query
restart/disconnect behavior, OIDC live-provider login and large-history load
benchmarks were not exercised by this UI slice. A separate discovered truncated
readiness-summary issue is tracked in #66; it does not alter this layout proof.

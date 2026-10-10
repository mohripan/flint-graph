# First conversation thread UI verification

Scope: #99 under #73/Milestone 27, following ADR 0028. This is the first
capability-gated thread UI, not broad memory, GPT/Claude parity or production
accessibility qualification. #62/#73/#74/#75/#82 remain open. Queued server-side
execution authorization hardening is separately tracked in #100.

## Delivered behavior and browser evidence

Real conversation/turn/run IDs drive the transcript, discovery and member rename;
no adjacent standalone runs are synthesized into chats and no client transcript
is sent to generation. Independent history and an older-backend fallback remain.
Selected IDs alone persist per workspace. New chat is isolated and does not delete
history; refresh/reopen are read-only. Safe retry preserves a single attempt key.
Queued resume uses the existing run; queued cancel and request-bound stop remain
distinct. Stop waits for read-only refresh to establish terminal backend status.

External HTTP-seam browser regressions passed at 390/1280px: ordered reopening,
original/resolved question display, scoped repeated `c1` IDs, lazy sources/full
excerpts, send/retry, new chat, title search/rename, conversation/turn paging,
selected-ID reload, explicit queued recovery/cancel, untrusted draft suppression,
stop/refresh, denied access clearing, stale chat/source responses across selections
and workspaces, read-only viewer actions, HTML-looking text, long/unbroken content,
bottom-aware following and Jump to latest. Answers and full quotes share the
primary transcript scroller; the composer remains visible. Final long-title
mobile regression keeps New chat on one line.

The separate standalone-history browser suite passed desktop/mobile shell,
long-answer/source scrolling, history search/paging/outcomes and delayed workspace
isolation. Browser fixtures make no model calls and do not use a human's session.
Two interrupted concurrent runs timed out at the browser CLI boundary; sequential
reruns passed. A screenshot-recapture script had a repeated top-level variable
declaration; it was corrected and rerun read-only. Neither was counted as passing.

## Fresh real-backend/model UI smoke

Used existing public FinQA historical excerpts only: workspace
`2eab2f78-208e-4eb9-97a2-087e40af0525`, active index
`fc8aa4e9-6b7f-4283-99cf-efc850a472e1`, 100 completed coverage rows.
These are pinned historical excerpts, not complete annual reports or current
financial guidance. No private document was read, restored or reuploaded.

The actual frontend submitted, renamed and followed up in conversation
`a1a002b0-6489-4687-99de-0f9ab345d70e` against the configured local Gemma/Ollama
answer/support service (8192 context); deterministic-test 384-dimensional
embeddings and the existing active retrieval setup were unchanged.

| Turn / run | Observed result | Provider invocations / input / output |
| --- | --- | --- |
| `3cee4d38-ee82-4ee7-baae-d15925583179` | 2017 RRP revenue excluding excise taxes: $3.6 billion; independent | 3 / 5958 / 243 |
| `a00f649f-8d6f-4d4e-8b42-7843a93d9c88` | Original prior-year question resolved to 2016: $733 million | 3 / 5508 / 138 |
| `da768a95-54b0-47f0-9233-a98d544bfe37` | Same elliptical question in a new chat: clarification, no citations | 0 / 0 / 0 |

New conversation `438e7830-1793-4067-8449-fa4b64f0cc8a` did not inherit old context.
All three runs completed with complete provider-usage accounting; both substantive
answers had active sources and zero persisted unsupported claims. This is bounded
smoke evidence, not a full model-quality guarantee or an attested monetary cost.
Reopening and reloading the original thread retained both server turns, made no
new mutation/stream request and left usage unchanged. Coverage stayed at 100.

Desktop/mobile screenshots were inspected. The first mobile inspection found
New chat wrapping next to a long title; the final header regression and read-only
recapture verified the corrected layout. Detailed JSON/screenshots and owned
verification scripts are gitignored under `notes/`; only public/synthetic data
was captured. The frontend remains available on localhost:5173.

## Verification commands

Passed in this change session:

- `uv run pytest -q --tb=short`: 914 passed, 15 skips.
- PostgreSQL opt-in `uv run pytest -q tests/integration/test_conversations_api.py --tb=short`: 27 passed, two SQLite-only concurrency skips.
- `uv run ruff check .`; `uv run mypy`: clean, 160 source files.
- `uv lock --check`; deterministic Acme evaluation quality gate.
- `FLINT_GRAPH_ENV=test uv run alembic upgrade head --sql`: 1061 lines, no migration change.
- `docker compose config --quiet`; `git diff --check`.
- Frontend `npm test`: 10 passed; `npm run typecheck`; `npm run build`.
- `npm run test:conversations`; `npm run test:browser`; final `--scroll-only` regression after the mobile-only style correction.
- Real-model browser smoke and read-only screenshot/reopen verification.

Not run for this frontend-only slice: another 12-case standalone nightly capture,
remote deployment/OIDC-browser login, production accessibility certification,
large-history load benchmarking, private-corpus tests, local optional telemetry
fan-out or paid-provider checks. Existing offline/nightly qualification remains
separate. CI status is recorded in the issue after pushing; no unobserved green
CI or full parent acceptance is claimed by this report.

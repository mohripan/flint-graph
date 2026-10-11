# Credential-bearing URL intake verification

Scope: #103, Milestone 29. `HTTPURLFetcher` rejects any parsed username or
password before DNS checks or HTTP dispatch, for the original URL and every
redirect target. Empty user information, username-only, password-only and
percent-encoded values are rejected. The private-network development opt-in
cannot bypass this guard. The error names the policy, not submitted credentials.
Ordinary permitted URLs, redirect limits and body-size limits remain unchanged.

This is not connection-bound DNS enforcement. DNS rebinding, ambient proxy
behavior, transport-wide deadlines and production egress qualification remain
#104 and the larger agent-security track. No third-party attack was attempted.

## Automated verification

- Tests were added before implementation: ten original-URL cases failed because
  the HTTP transport was contacted. The guard made them pass.
- `uv run pytest -q tests/unit/test_url_fetcher_security.py tests/integration/test_intake.py --tb=short`:
  32 passed. Includes redirected credentials, allowed credential-free URLs and
  API rejection without documents or object writes. One initial test assumed a
  nonexistent job-list endpoint; its assertion was corrected, not the API.
- `uv run pytest -q --tb=short`: 994 passed, 15 skipped in 134.45s. Skipped
  integration checks were not reported as live/production passes.
- `uv run ruff check .`, `uv run mypy` (160 source files), `uv lock --check`,
  deterministic Acme evaluation gate, offline migration SQL, Compose validation
  and `git diff --check` passed. No schema migration was needed.

## Running API verification

Only the API was rebuilt using `docker compose up --build --no-deps -d api`.
Existing model selections were preserved; no database, worker, projection or
corpus was recreated. The tested working-tree image was
`sha256:5b237acef1c6effb382d874e8d7ace0b922449ee520fe6345d32475775c0436c`;
its migration head was `0016_conversation_ledger`. It included the new guard
before the corresponding commit; this image is not a claim about a later commit
hash. Doctor reported available configured providers and 100 completed public
coverage rows, with explicit development-auth/deterministic-model caveats.

An owned disposable local HTTP server accepted only synthetic placeholder
credentials. Public workspace `2eab2f78-208e-4eb9-97a2-087e40af0525` was used:

- Credential-bearing original URL: HTTP 400, zero sentinel HTTP requests.
- Credential-free redirect source: one HTTP GET without `Authorization`, then
  HTTP 400 for its credential-bearing target; no target HTTP request.
- Before/after: 100 documents, 100 ingestion jobs and 400 MinIO objects in this
  workspace's prefix; search readiness was unchanged. No ingestion or model
  work was dispatched. The owned server was closed afterward.

Local evidence: `notes/url-credential-denial-live-2026-10-11.json` and the owned
`notes/verify_url_credentials_live.mjs` verifier. Raw notes are not repository
deliverables. No real credential, private document or third-party host was used.

Not rerun for this backend-only change: frontend unit/build/full browser suites
or a new answer-quality/model capture. Frontend remains running on localhost:5173;
the earlier read-only desktop/mobile reopen checks are separate evidence, not
this URL policy's acceptance. PostgreSQL-specific conversation tests were not
rerun; no conversation/auth/schema behavior changed. CI outcome is recorded in
the issue after push rather than assumed by this report.

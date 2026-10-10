# FlintGraph Frontend

A focused end-user UI for FlintGraph: sign in, choose a workspace, prepare
search, upload or ingest documents, ask streamed citation-bearing questions,
and inspect recent query history. Built with React, TypeScript, Vite, and
Tailwind CSS.

## Prerequisites

- Node.js 20.19+ or 22.12+ and npm
- The FlintGraph backend running and reachable at the default
  `http://localhost:8000`, including the outbox relay and ingestion worker for
  document processing.

From the repo root:

```bash
docker compose up --build
```

## Run The UI

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

The dev server proxies `/v1` and `/health` to the backend, so the browser talks
same-origin and no CORS configuration is needed on the API. If the backend is
not on `:8000`, point the proxy at it:

```bash
FLINT_GRAPH_API_TARGET=http://localhost:9000 npm run dev
```

## Auth Modes

The frontend defaults to local dev auth:

```bash
VITE_FLINT_GRAPH_AUTH_MODE=dev
```

For Keycloak or another OIDC provider:

```bash
VITE_FLINT_GRAPH_AUTH_MODE=oidc
VITE_FLINT_GRAPH_OIDC_AUTHORITY=http://localhost:8080/realms/flintgraph
VITE_FLINT_GRAPH_OIDC_CLIENT_ID=flintgraph-frontend
```

OIDC mode uses `oidc-client-ts`, redirects the user through the provider, and
sends access tokens with API requests and SSE streams.

## How It Maps To The API

| UI action             | Endpoint(s)                                                     |
| --------------------- | --------------------------------------------------------------- |
| List workspaces       | `GET /v1/workspaces`                                            |
| Create workspace      | `POST /v1/workspaces`                                           |
| Setup readiness       | `GET /v1/system-readiness`                                      |
| Prepare search        | `POST /v1/retrieval-index/bootstrap`                            |
| Backfill search       | `POST /v1/retrieval-index/backfill-active`, `GET /v1/index-backfills` |
| List documents        | `GET /v1/documents`                                             |
| Upload a file         | `POST /v1/documents/uploads`                                    |
| Ingest a URL          | `POST /v1/documents/from-url`                                   |
| Track ingestion       | `GET /v1/ingestion-jobs/{id}` and `POST .../cancel`             |
| Conversation history  | `GET /v1/conversations?limit=25&q=...&before_id=...`             |
| New conversation      | `POST /v1/conversations` (on first Send, not on New chat)        |
| Reopen / load turns   | `GET /v1/conversations/{id}`, `GET .../turns?after_id=...`        |
| Send a thread turn    | `POST /v1/conversations/{id}/turns`, then existing run SSE       |
| Rename a conversation | `PATCH /v1/conversations/{id}` (member or higher)                |
| Cancel queued turn    | `POST /v1/conversations/{id}/turns/{turn}/cancel`                 |
| Independent question  | `POST /v1/query-runs` then `GET .../events/stream` with `fetch()` |
| Query history         | `GET /v1/query-runs?limit=25&q=...&before_id=...`                 |
| Sources for an answer | `GET /v1/query-runs/{id}/provenance`                            |
| API health indicator  | `GET /health/ready`                                             |

The query stream is consumed via `fetch()` instead of `EventSource` because the
API requires headers for bearer auth and `X-Tenant-ID`. See `src/lib/stream.ts`.

When the backend advertises `conversation_ledger`, Ask shows workspace-shared
conversation history and ordered user/assistant turns. Search matches titles;
load older conversations and remaining turns with server cursors. New chat clears
the view without deleting saved history. A member may rename a shared title;
viewers can read existing threads but get no conversation write/execution actions.
Only selected conversation IDs are kept in local storage, separately per workspace.
Reopening/reloading/refreshing reads server state and never starts inference.

The transcript is the primary vertical scroller; the composer stays visible.
New content follows readers near the bottom, otherwise use Jump to latest. Each
answer has its own run-scoped citation links, lazy sources, expandable full source
excerpts and collapsed diagnostics. Model/source text is rendered as text, not HTML.
Original and interpreted questions are shown separately. Only delivered narrow
prior-year follow-ups are advertised, not general chained memory (#62/#75).

Send uses a stable request identity for safe lost-response retry, without sending
a client-side transcript. Queued turns offer explicit Resume/Cancel; Stop stream
only disconnects the current request. Refresh confirms actual backend state.
Switching workspace/chat or receiving 401/403 clears old data and aborts/ignores
outstanding requests. Durable background execution remains Milestone 18 work.
Server hardening of queued conversation execution is tracked in #100: hiding
controls is not authorization.

Independent question history preserves previous standalone results separately;
older/unavailable backends fall back to independent questions. These questions
have no follow-up memory, even when listed chronologically.

`npm run test:browser` uses an isolated pinned agent-browser session and synthetic
public-HTTP fixtures, with Vite already running. It checks mobile/desktop layout,
long-answer/source scrolling, history search/pagination/outcomes and delayed
workspace responses. It does not call models or alter a user's browser session.
`npm run test:conversations` uses the same isolated pinned browser approach for
thread send/retry, new-chat/reload isolation, title search/rename, both cursor
types, scoped sources, queued recovery, stop/refresh, revocation, stale chat/source
responses, viewer access, safe text and bottom-aware long-content scrolling.
Focused development runs accept `-- --discovery-only`, `-- --recovery-only`, or
`-- --scroll-only`; use the unfiltered command for complete qualification.

## Real vs. Stub Answers

Out of the box, `docker compose` runs deterministic answer and embedding
providers, so answers are useful for smoke testing but not model quality. To get
real grounded answers, run the backend with real providers such as Anthropic
for answers/support and OpenAI-compatible or Ollama embeddings. Changing
embedding provider/model/dimension requires preparing a compatible retrieval
index and running a backfill from the Setup page or API.

## Project Layout

```text
src/
  lib/        API client, auth, SSE streamer, workspace + job stores, types
  components/ UI primitives, workspace gate, progress trail, citations panel
  pages/      AskPage capability dispatcher, conversation/standalone Ask, setup/upload
  App.tsx     layout, navigation, health indicator
```

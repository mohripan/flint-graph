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
| Ask a question        | `POST /v1/query-runs` then `GET .../events/stream` with `fetch()` |
| Query history         | `GET /v1/query-runs?limit=25&q=...&before_id=...`                 |
| Sources for an answer | `GET /v1/query-runs/{id}/provenance`                            |
| API health indicator  | `GET /health/ready`                                             |

The query stream is consumed via `fetch()` instead of `EventSource` because the
API requires headers for bearer auth and `X-Tenant-ID`. See `src/lib/stream.ts`.

The Ask page has one primary vertical scroll area, naturally sized answers and
source columns, and collapsed run diagnostics below the answer. Open **Question
history** to search and load older questions; selecting one reopens its persisted
answer/provenance without creating a query or running a model. Refresh history
checks newly completed runs. **New question** clears the displayed result. Each
question is independent: conversation memory is planned in #62, not supplied by
chronological history. Workspace switches clear results and abort/ignore old
responses. Switching away during an active stream may interrupt request-bound
execution; durable background query execution remains Milestone 18 work.

`npm run test:browser` uses an isolated pinned agent-browser session and synthetic
public-HTTP fixtures, with Vite already running. It checks mobile/desktop layout,
long-answer/source scrolling, history search/pagination/outcomes and delayed
workspace responses. It does not call models or alter a user's browser session.

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
  pages/      AskPage, SetupPage, UploadPage
  App.tsx     layout, navigation, health indicator
```

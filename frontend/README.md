# AtlasRAG Frontend

A minimal, non-technical end-user UI for AtlasRAG: **Ask** questions with streamed,
citation-bearing answers, and manage **Documents** (upload files or ingest URLs, with
live ingestion status). Built with React + TypeScript + Vite + Tailwind CSS.

There is no authentication yet (by design). A "workspace" maps to a backend tenant and
is created on first use and remembered in `localStorage`.

## Prerequisites

- Node.js 18+ and npm
- The AtlasRAG backend running and reachable (default `http://localhost:8000`), including
  the outbox relay and ingestion worker so uploads actually process. From the repo root:

  ```bash
  docker compose up --build
  ```

## Run the UI

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

The dev server proxies `/v1` and `/health` to the backend, so the browser talks
same-origin and no CORS configuration is needed on the API. If the backend is not on
`:8000`, point the proxy at it:

```bash
ATLAS_API_TARGET=http://localhost:9000 npm run dev
```

## How it maps to the API

| UI action            | Endpoint(s)                                                        |
| -------------------- | ------------------------------------------------------------------ |
| Create workspace     | `POST /v1/tenants`                                                  |
| Upload a file        | `POST /v1/documents/uploads` (multipart, `Idempotency-Key`)        |
| Ingest a URL         | `POST /v1/documents/from-url`                                       |
| Track ingestion      | `GET /v1/ingestion-jobs/{id}` (polled), `.../cancel`               |
| Ask a question       | `POST /v1/query-runs` then stream `GET .../events/stream` (SSE)    |
| Sources for an answer| `GET /v1/query-runs/{id}/provenance`                               |
| API health indicator | `GET /health/ready`                                                 |

The query stream is consumed via `fetch()` (not `EventSource`) because the API requires
the `X-Tenant-ID` header, which `EventSource` cannot send. See `src/lib/stream.ts`.

## Real vs. stub answers

Out of the box, `docker compose` runs **deterministic (stub)** answer/embedding
providers, so answers will look like placeholder text. To get real, grounded answers,
run the backend with real providers (e.g. `ATLAS_QUERY_ANSWER_PROVIDER=anthropic`,
`ATLAS_QUERY_SUPPORT_PROVIDER=anthropic`, real embeddings, and `ANTHROPIC_API_KEY`),
which also requires a one-time embedding reindex. The UI itself is unchanged either way.

## Project layout

```
src/
  lib/        api client, SSE streamer, workspace + job stores, types
  components/ UI primitives, workspace gate, progress trail, citations panel
  pages/      AskPage, UploadPage
  App.tsx     layout, navigation, health indicator
```

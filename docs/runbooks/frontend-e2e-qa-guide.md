# Frontend end-to-end QA guide

This guide verifies the Milestone 10 user path from the browser.

## Setup

Start backend services:

```powershell
docker compose up --build
```

Start the frontend:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

## Deterministic smoke

The default Compose path uses deterministic providers. Use it to verify UI
states without live model services.

1. Create a workspace.
2. Open Documents.
3. Confirm Search readiness initially reports no searchable documents.
4. Upload a small Markdown, text, HTML, or PDF file.
5. Confirm the local job row moves through queued/running/completed or shows a
   clear failure.
6. Confirm Search readiness shows indexing/searchable state from the backend.
7. Ask a question only after the workspace is searchable.
8. Confirm the answer panel, source panel, progress trail, and diagnostics panel
   render.

## Ollama smoke

Use `docs/runbooks/local-ollama-rag.md` for provider settings and model pulls,
then repeat the browser flow with the discrete mathematics PDF at the repository
root.

Successful answers should include:

- streamed progress;
- final answer text;
- citation chips;
- source snippets;
- support decisions;
- run diagnostics.

If the answer abstains, the diagnostics panel should show whether retrieval,
context packing, citation repair, or support checking caused the abstention.

## API cross-checks

```powershell
curl.exe -sS http://localhost:8000/v1/search-readiness -H "X-Tenant-ID: <tenant-id>"
curl.exe -sS http://localhost:8000/v1/query-runs/<query-run-id> -H "X-Tenant-ID: <tenant-id>"
curl.exe -sS http://localhost:8000/v1/query-runs/<query-run-id>/provenance -H "X-Tenant-ID: <tenant-id>"
```

The query-run response should include `query_diagnostics`.

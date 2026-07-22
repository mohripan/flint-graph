# Local Ollama RAG runbook

Use this runbook to exercise the Milestone 10 local-first path without paid
model APIs.

## Models

Recommended baseline:

```powershell
ollama pull nomic-embed-text
ollama pull llama3.2
```

`nomic-embed-text` uses 768-dimensional embeddings. Do not reuse a retrieval
index version created for deterministic 384-dimensional embeddings.

## Start services

PowerShell:

```powershell
$env:FLINT_GRAPH_EMBEDDING_PROVIDER = "ollama"
$env:FLINT_GRAPH_EMBEDDING_MODEL = "nomic-embed-text"
$env:FLINT_GRAPH_EMBEDDING_DIMENSIONS = "768"
$env:FLINT_GRAPH_QUERY_ANSWER_PROVIDER = "ollama"
$env:FLINT_GRAPH_QUERY_SUPPORT_PROVIDER = "ollama"
$env:FLINT_GRAPH_QUERY_ANSWER_MODEL = "llama3.2"
$env:FLINT_GRAPH_QUERY_SUPPORT_MODEL = "llama3.2"
docker compose up --build
```

The Compose services talk to host Ollama at `http://host.docker.internal:11434`.

For CPU-constrained smoke tests, use a smaller installed local model and reduce
the query context:

```powershell
$env:FLINT_GRAPH_QUERY_ANSWER_MODEL = "gemma3:270m"
$env:FLINT_GRAPH_QUERY_SUPPORT_MODEL = "gemma3:270m"
$env:FLINT_GRAPH_QUERY_ANSWER_MAX_TOKENS = "160"
$env:FLINT_GRAPH_QUERY_CONTEXT_TOKEN_BUDGET = "350"
$env:FLINT_GRAPH_QUERY_MAX_CONTEXT_RECORDS = "1"
```

## Create a compatible active retrieval index

Create or activate a retrieval index version whose embedding provider, model,
and dimensions match the settings above. If documents were indexed under another
embedding contract, start an index backfill for the new version.

Useful inspection endpoints:

```powershell
curl.exe -sS http://localhost:8000/v1/index-versions -H "X-Tenant-ID: <tenant-id>"
curl.exe -sS http://localhost:8000/v1/search-readiness -H "X-Tenant-ID: <tenant-id>"
curl.exe -sS http://localhost:8000/v1/index-coverage -H "X-Tenant-ID: <tenant-id>"
```

## Frontend smoke

Start the UI:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

Manual flow:

1. Create a workspace.
2. Upload a small markdown or text document first, such as `README.md`.
3. Wait until the Documents page shows at least one searchable document.
4. Ask:
   - `What is FlintGraph?`
   - `What does the local Ollama setup do?`
5. Confirm final answers include citations and source text.
6. If an answer abstains, inspect the run diagnostics shown in the Ask page.

The sample discrete-mathematics PDF is useful as a heavier parser/indexing test.
On small local machines it can exceed the default parser timeout; increase
`FLINT_GRAPH_PARSER_TIMEOUT_SECONDS` before using it as the first smoke document.

## Expected failures

- `no_active_index`: create or activate a retrieval index version.
- `no_completed_coverage`: run ingestion/indexing or start a backfill.
- `indexing_in_progress`: wait for the indexing workflow to complete.
- `indexing_failed`: inspect `GET /v1/index-coverage` and worker logs.
- Ollama model missing: pull the configured model and retry.

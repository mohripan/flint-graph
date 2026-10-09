# Fresh query evaluation capture

This opt-in command runs **new queries**, including configured model calls, in an
already-ingested and indexed evaluation workspace. It does not import the corpus
or manufacture expected answers. Use a dedicated workspace and synthetic golden
documents. Hosted providers may incur cost. Never use customer/private documents
in recordings intended for GitHub or CI artifacts.

## Label manifest

Create a local JSON manifest after indexing the golden corpus:

```json
{
  "tenant_id": "11111111-1111-4111-8111-111111111111",
  "dataset_name": "acme-smoke",
  "dataset_version": 1,
  "document_labels": {
    "22222222-2222-4222-8222-222222222222": "acme-overview"
  },
  "chunk_labels": {},
  "entity_labels": {},
  "relationship_labels": {}
}
```

Replace the example UUIDs with actual workspace/document IDs and include every
retrieved source in the evaluation corpus. `chunk_labels` overrides document
labels for genuinely chunk-labeled datasets. The current smoke dataset uses
document labels, so multiple retrieved chunks from one document collapse to one
ranked logical hit. `entity_labels` maps canonical UUIDs to entity relevance labels.
Graph-summary citations without document identities require explicit
`relationship_labels`; the capture tool never guesses their source document.

Unmapped selected sources/entities and mismatched dataset versions fail capture.
Linked entities are diagnostic only, not graph-retrieval hits. Candidates with null
rerank rank are not included in post-rerank metrics. Scores describe the
post-rerank, pre-context-pack stage, not every raw retriever ranking.

## Capture and score

In OIDC mode, set `FLINT_GRAPH_EVAL_TOKEN` to a bearer token with access to the
evaluation workspace. The CLI reads it from the environment, not a command-line
argument. The token is never written into the recording. Use HTTPS remotely;
unencrypted HTTP is accepted only for literal loopback addresses.

```powershell
uv run flint-graph-eval capture --dataset evals/datasets/acme-smoke --manifest notes/acme-capture-manifest.json --base-url http://localhost:8000 --output notes/acme-fresh.jsonl --git-sha YOUR_DEPLOYED_REVISION
uv run flint-graph-eval run --dataset evals/datasets/acme-smoke --evaluations notes/acme-fresh.jsonl --experiment evals/experiments/acme-smoke.yaml --config-name fresh --report notes/acme-fresh-report.json
```

Use the revision actually deployed, not necessarily the checkout running the
capture CLI. Choose a new output filename for every capture. Existing recordings
and accepted baselines are never overwritten. All queries must complete before
the new recording is written; failed/cancelled/incomplete runs fail the command.
On failure, inspect the query run/events rather than retrying blindly: creation
and model execution may already have occurred. The default whole-query timeout
is 300 seconds (`--query-timeout` overrides it); current request-bound SSE can
cancel a run on timeout/disconnect.

JSONL is compatible with the existing offline scorer and adds capture metadata:
timestamps, dataset revision, query-run/index/workspace IDs, declared Git revision
and diagnostics. Retrieval labels come from persisted candidate ranks; final
citations come from answer provenance. All persisted claim support statuses are
counted, including partial/unsupported draft claims. Invalid/inactive final
citations are counted as invalid, never replaced with fabricated sources.

Provider token/cost accounting and exact model fingerprints are not added by this
capture command. Corpus import, projection-readiness polling, hosted live-model
capture in CI, and strategy comparisons remain milestone work. The offline PR
gate still uses its reviewed deterministic recording and cannot prove that a
deployment's ingestion/indexing/model services are healthy.

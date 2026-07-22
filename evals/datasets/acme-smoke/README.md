# Golden dataset: `acme-smoke` (v1)

A small, hand-labeled golden set for the evaluation platform (Milestone 09). Six short
source documents plus ten labeled queries covering all four query types.

## Layout

- `dataset.yaml` — metadata (name, version, tenant, corpus dir).
- `corpus/*.md` — the fixed source documents. Each is short enough to chunk into a single
  chunk. The **filename stem is the document `external_id`** (e.g. `acme-overview`).
- `queries.jsonl` — one labeled `GoldenQuery` per line.

## Labeling convention (read before adding queries)

Pipeline-assigned chunk IDs and canonical entity UUIDs are **not stable** across
ingestions, so labels are recorded at a stable granularity:

- `relevant_chunk_ids` and `must_cite_sources` hold **document external_ids** (= corpus
  filename stem), i.e. relevance is scored at document granularity.
- `relevant_entity_ids` holds **canonical entity names** (e.g. `Acme Corporation`).

The evaluator (wired in a later phase) maps every retrieved chunk, linked entity, and
answer citation back to these stable identifiers before computing metrics. Abstain-expected
queries carry no `relevant_chunk_ids` and no `expected_answer`.

## Query coverage

| type | count | examples |
|------|-------|----------|
| factoid | 4 | HQ, founder, CEO, Globex location |
| multi_hop | 2 | acquirer's HQ / founder (acquisition doc → overview) |
| entity | 2 | "What is Acme?", "Tell me about Globex" |
| abstain_expected | 2 | revenue (absent), Initech CEO (absent) |

## Reproducible ingestion

Ingest into tenant `eval-acme`, one document per corpus file, with `external_id` set to the
filename stem. With the stack running (`docker compose up`) and the tenant created:

```bash
for f in corpus/*.md; do
  stem="$(basename "$f" .md)"
  curl -sS -X POST http://localhost:8000/v1/documents/uploads \
    -H "X-Tenant-ID: $EVAL_TENANT_ID" \
    -H "Idempotency-Key: eval-acme-$stem" \
    -F "title=$stem" -F "external_id=$stem" \
    -F "file=@$f;type=text/markdown"
done
```

Ingestion is idempotent on `(tenant, external_id, content)`, so re-running is safe. An
automated ingestion + evaluation entrypoint (`flint-graph-eval`) arrives with the CLI phase.

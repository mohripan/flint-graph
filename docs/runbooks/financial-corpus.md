# Public financial-report corpus

`flint-graph-corpus` collects the pinned official FinQA public dev/test release.
It does not call providers, download models, upload files, or execute downloaded
code. Keep the output under gitignored `notes/` or an explicitly managed data
directory. Existing outputs are rejected, not overwritten.

```powershell
uv run flint-graph-corpus download --output notes/finqa-public-0f16e286 --json
uv run flint-graph-corpus verify --directory notes/finqa-public-0f16e286 --json
```

Defaults: at most 2,000 distinct excerpts, 32 MiB total source bytes, 20 MiB per
source, one request in flight, 180 seconds of overall download time and 30 seconds
per HTTP operation. Hard ceilings are 5,000 examples/excerpts, 600 download
seconds, 1 MiB per rendered excerpt, 32 MiB rendered corpus and 32 MiB annotations.
`--max-documents`, `--max-source-bytes`, and `--timeout-seconds` can reduce budgets.
`truncated` distinguishes selected from available examples. A failed collection
has no complete manifest; inspect it and choose a new output path for a retry.

The pinned release yielded 2,030 examples, 679 distinct evidence excerpts and
409 company/year reports on 2026-10-10. This is **not 409 full annual reports**.
Source bytes totaled 25,350,868; rendered evidence totaled 2,776,454 bytes.

| Artifact | Purpose |
| --- | --- |
| `corpus/*.md` | Only uploadable evidence: source text/table and report identity |
| `raw/dev.json`, `raw/test.json` | Original public source records, including labels; never ingest |
| `annotations.jsonl` | Expert labels linked to evidence; never ingest |
| `LICENSE`, `ATTRIBUTION.txt` | Dataset release notice and original-issuer rights caveat |
| `manifest.json` | Pinned revision, source/file hashes, example provenance and counts |

Verification is offline. It checks file/path/size bounds, SHA-256 hashes,
independently pinned raw Git blob IDs, and exact re-rendered evidence membership.
Treat the artifact directory as immutable; do not add gold answers to its corpus.
Do not use original labels as generated-answer evidence. Public benchmark
contamination means a high score alone is not production quality proof.

## Explicit bounded ingestion

Export at most 100 verified excerpts. Gold annotations/raw records are not copied.
`queries.jsonl` is intentionally empty until a separately reviewed quality suite
is supplied. Export does not mutate a workspace.

```powershell
uv run flint-graph-corpus dataset --directory notes/finqa-public-0f16e286 --output notes/finqa-batch-0 --max-documents 100 --offset 0 --json
```

Once ingestion services are ready, explicitly prepare that batch through the
public API. This creates a **new dedicated evaluation workspace**, uploads files,
and waits for jobs, coverage and lexical/vector visibility. Local deterministic
embeddings do not prove real financial retrieval quality. In OIDC deployments,
set `FLINT_GRAPH_EVAL_TOKEN` to an authorized bearer token without committing it.

```powershell
uv run flint-graph-eval prepare --dataset notes/finqa-batch-0 --base-url http://localhost:8000 --output notes/finqa-batch-0-live-manifest.json --prepare-timeout 900
```

Remote APIs require HTTPS. The preparation manifest is created only after success;
failed workspace/job evidence remains available for inspection. Batch offsets can
export the remaining corpus, but each ordinary `prepare` creates a separate
workspace. Do not claim that all downloaded documents are indexed together.

The first real 100-file preparation exposed a pre-existing cross-document evidence
ID collision. [#55](https://github.com/mohripan/flint-graph/issues/55) tracks the
fix; see the [delivery report](../reports/2026-10-10-financial-corpus-delivery.md).
Do not weaken uniqueness or delete the failed workspace to hide this evidence.

Source details and licensing: [ADR 0016](../adr/0016-pinned-public-financial-corpus.md).

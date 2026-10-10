# Financial corpus collection: 2026-10-10

Tracking: [#54](https://github.com/mohripan/flint-graph/issues/54).

Live download command:

```powershell
uv run flint-graph-corpus download --output notes/finqa-public-0f16e286 --max-documents 2000 --json
uv run flint-graph-corpus verify --directory notes/finqa-public-0f16e286 --json
uv run flint-graph-corpus dataset --directory notes/finqa-public-0f16e286 --output notes/finqa-batch-0 --max-documents 100 --json
```

Passed: 25,350,868 source bytes; 2,030 public examples; 679 distinct rendered
evidence files; 409 company/year reports; 2,776,454 evidence bytes; no truncation.
The explicit batch contains 100 files, no answer annotations/raw records, and
an empty query suite (not a quality gate). All artifact files remain gitignored.

Pinned official revision: `0f16e2867befa6840783e58be38c9efb9229d742`.
Source SHA-256 hashes measured after independently pinned Git blob validation:

| Source | Bytes | SHA-256 |
| --- | ---: | --- |
| LICENSE | 1,067 | `92c0e67bd762c15c07ba60de09558338315a8ebf99aac4f51f487179809ac087` |
| dataset/dev.json | 10,954,658 | `a847fb7e0d61a3125a1e2909852df6b89f1ee64d2c5ff1bf689e332214deee51` |
| dataset/test.json | 14,395,143 | `831dbfb2e785dbc227f895ce3f24046433467aec67b09db2bd6ac7692a8a30dc` |

## Live ingestion exposed a blocker

```powershell
uv run flint-graph-eval prepare --dataset notes/finqa-batch-0 --base-url http://localhost:8000 --output notes/finqa-batch-0-live-manifest.json --prepare-timeout 900
```

Failed, not passed: workspace `ff05efae-e8ae-4577-8801-7af5e3a29e35` remains
inspectable. Worker traces show `uq_evidence_spans_stable_id` rejects identical
quote/chunk/offset identities across distinct documents in the same tenant.
Failure recording subsequently encounters `PendingRollbackError`. No successful
preparation manifest was emitted. [#55](https://github.com/mohripan/flint-graph/issues/55)
must fix the identity/transaction boundary before a fresh retry can qualify this
ingestion flow. No user data, jobs or volumes were removed.

## Verification and limitations

Tests precede behavior changes. Focused corpus/CLI tests: 18 passed, covering
answer separation, deduplication/provenance, source corruption, redirects,
size bounds, non-overwrite, safe paths, tampering (including manifest rewrites),
bounded evidence-only export and truncated-count reporting. Wider gates passed:
`uv run pytest -q` (620 passed, 6 skipped), `uv run ruff check .`, `uv run mypy`
(149 source files), `uv lock --check`, the unchanged deterministic eval/baseline
gate, `uv run alembic upgrade head --sql` with deterministic providers, and
`docker compose config --quiet`. Migration SQL validation did not migrate data.

No frontend changes/browser QA, full annual-report archive, paid inference,
model downloads, or real-embedding financial quality measurement were performed.
Fresh nightly black-box capture remains #53. Preserve MIT release notices;
original issuer rights and public-benchmark contamination remain explicit limits.

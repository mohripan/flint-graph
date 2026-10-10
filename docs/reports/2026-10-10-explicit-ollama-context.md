# Explicit Ollama query context qualification

Tracking: [#95](https://github.com/mohripan/flint-graph/issues/95).
Decision: [ADR 0025](../adr/0025-explicit-ollama-query-context.md).

## Delivered

The factory-to-provider boundary now sends an explicit configurable `num_ctx`
for normal/streaming answers and support checks. Default: 8192, bounded to
2048..131072. Ollama settings reject context smaller than packing estimate plus
output plus 2048 overhead reserve. This is not exact tokenizer admission or
proof that all supported models/hardware can handle the default. Other providers,
extraction and embedding configuration are unchanged.

Tests first reproduced the omitted option separately for answer, stream and
support, then missing startup validation for each Ollama role. Strict schemas,
prompts, citation/support checks, corpus, output limits and scoring rules remain
unchanged. Only the API was rebuilt; existing provider settings were preserved.

## Live evidence

Fresh reports (gitignored, historical failures retained):

| Capture | Individual cases | Input/output tokens | p50 / p95 latency |
| --- | --- | --- | --- |
| `notes/financial-nightly-explicit-context-2026-10-10.json` | 12/12 passed | 60312 / 2745 | 9.763s / 17.825s |
| `notes/financial-nightly-explicit-context-restart-2026-10-10.json` | 12/12 passed | 60312 / 2745 | 10.294s / 20.722s |

Both format-3 captures have complete query invocation accounting, useful-answer
rate 1.0, both abstention cases correct, citation checks passing and all foreign
workspace probes returning 404. These totals include the full current embedding /
answer / support accounting scope. Embeddings remain deterministic, and local
compute is unpriced. Do not compare them as billing totals with old format-2
answer/support-only captures or claim a release-wide quality/performance result.

Between captures, verified the executable, command line and port ownership of
the Ollama process launched during local restoration, then stopped only that
owned `ollama serve` process and relaunched it hidden with no host context override.
Its `/api/ps` initially had no loaded models. After fresh API requests, effective
model context was again 8192. Observed model VRAM allocation: 7,905,979,924 bytes;
this is one loaded model's reported allocation, not a capacity benchmark.
The API/database/frontend and all source data were left in place.

Final first-case run: `d42dec41-e798-45ed-9f83-41130b863cc4`.
Final arithmetic run: `e930a2a0-4cd8-4925-933a-c599d23e00f7`.
Installed model digest: `2835c50a7b13c1e9c8ab58a4d08368e374ae5f33ce055afb0b8081bc006aef9f`.
Role/model fingerprint: `669a19cae19de22a089a9c681f1e6d37a1d5412ba479ff0de316c3d988749833`.
That existing fingerprint does not include generation settings; the changed
8192-token request window is disclosed here, not hidden as identical deployment
behavior. Rubric fingerprint remains
`bf4548f3bafb3dc054548538874f4a62643490cf76934eac36cd83a85633fb1f`;
policy fingerprint remains
`5d574de7251e4aa9eca5ed777ffeec2dec1312fdceff9a337b7e780f478ac5b1`.

The earlier 4096-window schema failures remain failures. Improvement with explicit
capacity is consistent with the mismatch hypothesis, but does not independently
prove their cause. No raw provider response, prompt or private source was logged
to investigate them.

## Checks

- `uv run pytest -q --tb=short`: 865 passed, 13 skipped.
- PG-enabled query API / usage accounting suite: 91 passed, 3 skipped.
- Focused configuration, factory and Ollama adapter tests: 41 passed.
- `uv run ruff check .`, `uv run mypy` (156 files), `uv lock --check`: passed.
- AGENTS.md Acme deterministic eval: passed; baseline unchanged.
- `FLINT_GRAPH_ENV=test uv run alembic upgrade head --sql`: passed, 1026 lines.
- `docker compose config --quiet`, `git diff --check`: passed.
- Real API captures and effective loaded-context/restart checks: passed.
- Frontend HTTP 200 at `http://localhost:5173`, left running. Local frontend
  tests/typecheck/build skipped: no frontend change.
- Real embedding / hosted-provider / hardware-scale qualification skipped;
  no installed embedding model, paid calls, downloads or hardware changes.
- External nightly deployment and reviewed approval remain #53.

# Durable query invocation accounting

Tracking: [#94](https://github.com/mohripan/flint-graph/issues/94).
Decision: [ADR 0024](../adr/0024-durable-query-invocation-accounting.md).

## Outcome

Query embeddings, generation and nonempty support checks now commit an invocation
before dispatch, independently of the execution transaction. Failures and
cancellation retain explicit unknown usage. Matching expected operations and
known terminal usage are required for complete accounting. Numeric zero alone
does not attest a free call, and complete token accounting does not mean priced
cost accounting. Tenant-scoped invocation inspection contains no query or vector.

Regression tests preceded implementation: missing real-provider usage, durable
rollback/cancellation/retry accounting, multi-clause API execution, tenant
isolation, replay idempotence, and nightly completeness checks. Live streaming
exposed a parent-row/FK lock conflict before support dispatch. A failing streaming
regression reproduced it; committing provisional draft events before independent
accounting fixed it without trusting those events or committing every token.

## Live evidence and limitations

The existing public FinQA workspace retains 100 searchable document versions.
No private document was queried, restored or re-uploaded. The existing installed
Gemma model was used for answer/support; embeddings remain deterministic.

Authorized API inspection confirms complete accounting for two post-fix runs:

| Run | Input tokens | Output tokens | Invocations |
| --- | ---: | ---: | --- |
| `c02161b0-3ac3-469d-a65a-0dfe691eca9f` | 5934 | 239 | embedding, answer, support |
| `4c050f9a-a4f9-4500-853b-4044017f9bfb` | 5983 | 224 | embedding, answer, support |

Both have one execution attempt, matching expected/recorded operation counts,
zero unknown events and three unpriced events. Their embedding counts are known
zero local computation, not evidence of real embedding quality or free inference.

Environment interruption cancelled run
`634e8938-6302-46d0-b214-b7a18e388bfd` after generation. All three invocation rows
survived; support is cancelled/unknown, and accounting is correctly incomplete.
The two preceding completed runs survived the service restart as well.

After restoring the host Ollama service, two fresh captures failed on the first
case with invalid structured generation. Runs
`52e95108-ac8d-4ec5-af9e-d419cea36af0` and
`a38d3533-33af-46f3-a6b0-d0e15a8d0860` retain failed/unknown answer invocations,
null cost and incomplete accounting; support was not dispatched. Retained reports
are `notes/financial-nightly-invocation-accounting-resumed-2026-10-10.json` and
`notes/financial-nightly-invocation-accounting-warm-2026-10-10.json`.
The interrupted intermediate capture did not produce a final report.

These are not passing 12-case quality captures. The restarted model was observed
with a 4096-token context; successful pre-restart generation reported 5058/5265
input tokens. The adapter did not set `num_ctx`. This is a reproducibility gap
requiring separately tracked context configuration and fresh qualification, not
proof that context truncation caused the schema failure. Rubrics, source corpus,
policy, model digest and old recordings were not changed to conceal failures.

## Verification

- `uv run pytest -q --tb=short`: 859 passed, 13 skipped.
- `FLINT_GRAPH_PG_INTEGRATION=1 uv run pytest -q tests/integration/test_query_api.py tests/integration/test_usage_accounting.py --tb=short`: 91 passed, 3 skipped.
- `uv run ruff check .`: passed.
- `uv run mypy`: passed, 156 source files.
- `uv lock --check`: passed.
- The AGENTS.md Acme deterministic evaluation command: passed; baseline unchanged.
- `FLINT_GRAPH_ENV=test uv run alembic upgrade head --sql`: passed, 1026 lines.
- `docker compose config --quiet` and `git diff --check`: passed.
- Real API invocation inspection, persisted success/failure/cancellation evidence:
  passed. Frontend `http://localhost:5173`: HTTP 200, left running.
- Frontend tests/typecheck/build: skipped locally; no frontend changes.
- Real embedding qualification: skipped; no embedding model installed. No paid
  provider was enabled. External nightly activation/human review remain #53.

Parent reservations, transport-level retries, crash recovery, caching and cost
optimization remain separate work (#82/#83). Request-bound SSE is not converted
to durable execution by this accounting boundary.

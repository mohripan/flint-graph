# Milestone 25: Search and inference platform performance

Status: planned; implementation issues are delivered independently.
Track: platform.
Epic: [#35](https://github.com/mohripan/flint-graph/issues/35).
Design: [ADR 14](../adr/0014-measured-search-and-inference-platform.md).

## Issue queue

| Issue | Scope | State |
| --- | --- | --- |
| [#44](https://github.com/mohripan/flint-graph/issues/44) | Add a vLLM-compatible answer and support provider adapter behind configuration | planned |
| [#45](https://github.com/mohripan/flint-graph/issues/45) | Benchmark vLLM versus Ollama on a fixed grounded workload | planned |
| [#46](https://github.com/mohripan/flint-graph/issues/46) | Build large-corpus tenant-filtered lexical and vector retrieval benchmarks | planned |
| [#47](https://github.com/mohripan/flint-graph/issues/47) | Add measured OpenSearch shard, refresh, alias and index lifecycle operations | planned |
| [#63](https://github.com/mohripan/flint-graph/issues/63) | Measure reference-only Temporal payloads, history growth and replay/conversation budgets | planned |
| [#82](https://github.com/mohripan/flint-graph/issues/82) | Atomic parent-wide cost/resource reservations and measured optimizations | planned |
| [#83](https://github.com/mohripan/flint-graph/issues/83) | Tenant-safe KV/prefix/answer cache qualification | planned |
| [#94](https://github.com/mohripan/flint-graph/issues/94) | Durable query embedding/generation/support invocation accounting and honest completeness | delivered |
| [#95](https://github.com/mohripan/flint-graph/issues/95) | Explicit Ollama query context capacity and restart reproducibility | delivered |

## Acceptance and boundaries

Run reproducible 10k/100k/1m-chunk comparisons as hardware permits; isolate
tenant/deletion filters; qualify optional vLLM with grounded-answer and support
tests; publish latency, recall, quality and resource evidence. Ollama remains
supported.

Coordinate M16/M17/M21/M22. Capacity targets and vLLM adoption require hardware/workload evidence; do not claim performance from the tiny smoke corpus.

#94 uses the existing PostgreSQL ledger with independent writer sessions,
pre-dispatch attempt records, idempotent terminal updates and explicit unknown
usage. Coordinated queries account for every embedding clause; generation and
support checking use the same durable boundary. Nightly accounting scope is
versioned separately from answer quality. See [ADR 0024](../adr/0024-durable-query-invocation-accounting.md).
This does not implement #82 reservations, #83 caches or real-embedding performance
qualification. Legacy rows/captures are not silently attested or re-scored.


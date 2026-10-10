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

## Acceptance and boundaries

Run reproducible 10k/100k/1m-chunk comparisons as hardware permits; isolate
tenant/deletion filters; qualify optional vLLM with grounded-answer and support
tests; publish latency, recall, quality and resource evidence. Ollama remains
supported.

Coordinate M16/M17/M21/M22. Capacity targets and vLLM adoption require hardware/workload evidence; do not claim performance from the tiny smoke corpus.


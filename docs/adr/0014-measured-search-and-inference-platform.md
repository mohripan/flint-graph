# ADR 0014: Measured search and inference platform

- Status: accepted direction; serving-engine adoption deferred to benchmarks
- Date: 2026-10-10
- Track: platform; Milestone 25; epic [#35](https://github.com/mohripan/flint-graph/issues/35)

## Context

Lots of documents require fast tenant-filtered retrieval. M17 plans native
pgvector and optional pgvectorscale; current vector reads use Neo4j, lexical reads
use OpenSearch, and PostgreSQL remains authoritative. There are no large-corpus
results establishing a throughput or latency guarantee. Local Ollama answers
work, but a serving-engine switch does not repair retrieval or faithfulness.

## Alternatives and decision

Keep Ollama as the local path. Add a configurable, authenticated vLLM-compatible
HTTP adapter at the existing provider boundary, rather than rewriting the
harness or making vLLM mandatory. Retain Anthropic and deterministic providers.
Server/model readiness, structured answers/support decisions, streaming,
timeout/cancellation, usage and malformed-output abstention must behave the same.
No server-specific permissive output path may bypass support checking.

Compare vLLM and Ollama on pinned model/revision/tokenizer/quantization and actual
available hardware. Record quality, TTFT, verified-output latency, concurrency,
throughput, queueing, memory and errors. Model/server limits determine feasible
hardware; this ADR does not authorize GPU rental or model downloads. Docker
serving is a deployment option, not proof the current Windows host is compatible.
Adopt vLLM for a controlled deployment only after the quality/capacity gates pass.

Retrieval benchmarks compare lexical plus current Neo4j, pgvector exact/ANN, and
optional pgvectorscale on 10k/100k/1m chunks as resources permit, with skewed
tenants, selective filters, deleted versions, churn and concurrency. Use exact
search as the recall reference. Report hardware, dimensions, p50/p95/p99,
freshness, build/disk/RAM costs and skipped scales. Tune OpenSearch bulk/refresh/
shards/aliases from this evidence. Operational ELK logging is a separate M24
decision; it does not replace or co-mingle corpus indexes.

## Consequences

Two serving options cost adapter/compatibility maintenance but preserve local DX.
No headline performance claim until measured. M17/M21 own vector and corpus
contracts; M25 owns reproducible capacity evidence and serving qualification;
M22 owns distributed admission control, production Temporal and recovery.

## Sources

- [vLLM official Docker deployment](https://docs.vllm.ai/en/latest/deployment/docker/)
- [vLLM documentation](https://docs.vllm.ai/en/latest/)
- [pgvector](https://github.com/pgvector/pgvector)
- [pgvectorscale](https://github.com/timescale/pgvectorscale)


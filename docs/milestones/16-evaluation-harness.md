# Milestone 16: evaluate the running application

Status: in progress. Tracking: [issue #2](https://github.com/mohripan/flint-graph/issues/2).
Full acceptance criteria are in the [roadmap](../ROADMAP.md).

## Default-branch and frontend quality gates

[Issue #19](https://github.com/mohripan/flint-graph/issues/19) corrects CI push
triggers to include the actual default branch, `master`, as well as `main`.
Pull requests retain offline backend gates. CI additionally generates migration
SQL with explicitly deterministic answer/support providers, so credentials are
not required for a migration syntax check.

A separate frontend job installs locked dependencies on Node 22, runs outcome
tests, checks TypeScript, and builds the application. The outcome tests use the
existing TypeScript dependency and Node's test runner without adding a frontend
test framework. Workflow contract tests enforce the required commands.

Fresh full-application dataset capture, expanded quality cases, and strategy
comparisons are not delivered by this CI change and remain open milestone work.

## Persisted retrieval inspection

[Issue #20](https://github.com/mohripan/flint-graph/issues/20) adds the read-only,
workspace-authorized `/v1/query-runs/{id}/retrieval` endpoint. It returns persisted
candidate source IDs, per-retriever ranks, fusion/rerank scores and ranks, document
identities and graph endpoint identities. It includes uncited candidates and
duplicates, so evaluation tools can distinguish retrieval from answer citation
selection. Linked entities are reported separately; linking is not a retrieval hit.

The response excludes text previews, prompts, provider payloads and arbitrary
metadata. Foreign runs return 404. Queued runs have an empty candidate list;
inspection never starts execution. Null rerank ranks identify candidates that were
not selected, including deduplicated retriever copies. Ordering is deterministic.

## Fresh public-API query capture

[Issue #21](https://github.com/mohripan/flint-graph/issues/21) implements opt-in
`flint-graph-eval capture` against an already-indexed evaluation workspace. It
creates runs, consumes SSE, requires completed status, reads actual retrieval
rankings/provenance, validates golden-label mappings, and emits scorer-compatible
JSONL with run/index/revision metadata. It does not overwrite recordings or
baselines, leak bearer tokens, or treat entity links as retrieved graph evidence.

Tests exercise the public HTTP boundary and capture a real in-process query run
(deterministic providers and fixture projections), with optional PostgreSQL
coverage. This is not evidence of full upload-to-answer ingestion quality or
hosted-provider health. See the [capture runbook](../runbooks/fresh-query-evaluation.md).

## Dedicated corpus preparation

[Issue #27](https://github.com/mohripan/flint-graph/issues/27) adds opt-in
`flint-graph-eval prepare`. It validates the bounded local corpus, creates a
dedicated workspace, uploads through the real intake API, waits for every job
and coverage row, and probes lexical/vector projection visibility before
returning a new manifest. Source labels derive from upload IDs and canonical
entity identities, never expected answers. Failed/time-limited preparations leave
their workspace/job evidence inspectable and never delete unrelated data.

This automates the upload/control-plane path; quality claims still require actual
capture/scoring, not merely successfully prepared documents.

## Fresh local rehearsal

See the [2026-10-10 comparison report](../reports/2026-10-10-local-answer-quality.md)
for three fresh ten-query captures on the same real-ingested corpus. Answer
match/abstention improved, but the strict graph-retrieval/draft-support gate still
fails. Milestone 16 remains in progress; accepted baselines are unchanged.

## Nightly public financial black-box harness

[#53](https://github.com/mohripan/flint-graph/issues/53) now has an opt-in fresh
public-API gate, source-checked 12-case financial suite, real per-run usage,
model/corpus/index fingerprints, cross-workspace probes and redacted reports.
It replaces stale-recording scheduled scoring. Missing remote deployment settings
are explicitly unconfigured, not a pass. Activation, external human rubric
review and accepted performance baselines remain pending.

The full local rehearsal completed all 12 cases with useful-answer rate 0.9,
abstention accuracy 0.9167 and p95 latency 16.47 seconds; the strict gate failed.
[#59](https://github.com/mohripan/flint-graph/issues/59) and
[#60](https://github.com/mohripan/flint-graph/issues/60) track two-source synthesis
and ambiguous-query failures. See [the runbook](../runbooks/financial-nightly.md).

## Explicit rubric revisions

[#71](https://github.com/mohripan/flint-graph/issues/71) adds only the
source-consistent `rrps` alias to the two RRP concept groups. Numeric/unit and
whole-term boundaries remain strict. New format-2 captures identify their dataset,
rubric and policy fingerprints, without reversioning the corpus or changing old
captures, thresholds or baselines. A separate fresh 12-case run passed the gate
at 0.9 useful-answer rate; the independent arithmetic failure remains #70.
This is a scoring correction, not a model-quality improvement or completed
external human review. See [the review report](../reports/2026-10-10-financial-rubric-plural.md).

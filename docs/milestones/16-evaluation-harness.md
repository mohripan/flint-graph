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

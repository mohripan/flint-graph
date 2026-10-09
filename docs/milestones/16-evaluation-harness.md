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

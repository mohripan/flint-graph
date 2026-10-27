# ADR 0036: immutable authored revisions and recoverable conflicts

Status: accepted, 2026-10-27. Implements M31 #122 under the user's approved
narrative studio direction and autonomous continuation.

## Context

The M30 package/player proves authored games can run independently of models and
the backend. A studio now needs workspace-owned projects whose exact source can
be recovered and eventually released. Mutable JSON with last-write-wins edits
would lose concurrent author work and obscure which source produced a game.

## Decision

PostgreSQL stores bounded canonical text/notices snapshots as append-only
revisions, with the existing M30 package hash. A mutable project points at its
current head. Every save supplies its base revision and idempotency UUID; a scoped
row lock serializes sequence allocation and head changes. Same-project/workspace
composite references prevent attaching foreign parents or heads. PostgreSQL
triggers reject ordinary revision updates/deletes; projects are archived.

A stale valid save is retained as an immutable conflict revision, with its base
and observed head. The API commits it and returns 409 with a recovery ID while
preserving the current head. Exact retries replay the recorded result. Adopting
or merging work creates another revision; it never rewrites the original. A
transport failure is retried with the same key because commit outcomes can be
uncertain.

Use existing signed-identity workspace authorization and roles. Source is a
strict JSON string rather than a permissively pre-decoded object, preserving M30
duplicate/type/limit checks. This first hosted API accepts text-only packages;
asset objects/approvals come through the separate asset-library boundary. No
models, retrieval readiness, background workflow or hosted compiler is required.

## Consequences and qualification

Old work and both sides of a conflict remain recoverable, at the cost of bounded
full snapshots per save and explicit client conflict handling. Retention/privileged
purge, collaborative text merging, hosted builds, assets and releases remain later
work. Database owners can change DDL; the trigger is not protection against them.

The API adds early bounded ASGI body coalescing, including missing/false lengths
and empty-frame amplification; normalized, hashed and capacity-bounded coarse
rate buckets; and safe database-error responses/hidden SQL parameters. These do
not replace production gateway quotas or hosted-code isolation. Audit metadata
contains IDs/hashes, not prose.

Actual PostgreSQL migration, FK/immutability and two independently authenticated
queued writers were exercised, alongside an actual loopback HTTP workflow.
See the [contract](../architecture/narrative-project-contract.md),
[focused design](../superpowers/specs/2026-10-27-narrative-project-revisions-design.md)
and [delivery report](../reports/2026-10-27-narrative-projects.md).

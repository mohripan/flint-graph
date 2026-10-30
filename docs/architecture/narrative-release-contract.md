# Narrative release control plane

M31 #124, initial ledger/API slice, migration `0018_narrative_releases`.
The [focused release design](../superpowers/specs/2026-10-30-narrative-releases-design.md)
defines the complete target. This document describes the implemented subset only.

## Available commands

Under `/v1/narrative/projects/{project_id}/releases`:

- `POST ""`: member or higher, `{revision_id, idempotency_key}`, 202 with immutable
  release identity plus the initially accepted queued job. An explicit validated
  older/conflict revision can be selected; project head is unchanged.
- `GET ""`: viewer or higher, `limit=1..100`, optional `before_id` and
  `include_archived`. Lists compact release/build identity and latest job metadata.
  Source/notices, object keys, engine paths and execution tokens are omitted.
- `GET /{release_id}` and `GET /{release_id}/jobs[/{job_id}]`: scoped item/latest
  and attempt history. Job lists accept bounded limit and an owned-job cursor.
- `GET /{release_id}/jobs/{job_id}/events`: ordered safe events, bounded limit and
  `after_sequence=0..2147483647`. Oversized cursors return 422 before SQL binding.
- `POST /{release_id}/jobs/{job_id}/cancel`: member+, idempotent status response.
  Queued work becomes cancelled immediately; running work retains its fence and
  reports cancellation requested until worker cleanup. Completed work is unchanged.
- `POST /{release_id}/retry`: member+, `{idempotency_key}`, 202 with a separate new
  attempt only after failed/cancelled work. Pin identities remain unchanged.

These routes reuse the existing authenticated workspace boundary. A workspace
header alone is not authentication. Foreign project/revision/cursor reads return
404 after membership authorization. Archived project lists require the explicit
flag. New release requests on archived projects return 409; an already-authorized
accepted-key replay still works.

Building is disabled by default. Explicit operator settings are
`FLINT_GRAPH_NARRATIVE_RELEASES_ENABLED`,
`FLINT_GRAPH_NARRATIVE_RELEASE_BUILDER_IMAGE_DIGEST` (`sha256:` plus 64 hex),
`FLINT_GRAPH_NARRATIVE_RELEASE_TOOLCHAIN_SHA256` (64 hex), and
`FLINT_GRAPH_NARRATIVE_RELEASE_MAX_ACTIVE_JOBS_PER_WORKSPACE` (default 10, range 1..100).
Until the runner/relay delivery is complete, enabling these only admits durable
queue intent; it does not start a build. Ordinary API startup never invokes Docker
or downloads a toolchain. Missing configuration rejects new requests with 503.
Do not enable this experimental queue in a deployment expecting completed artifacts.

## Identity, transactions and replay

Release keys are scoped to project/workspace; retry keys are scoped to the release.
Intent hashes include the explicitly
selected revision, independent of current runtime configuration. Same key/different
revision returns 409. Accepted replay is resolved before configuration, archive or
admission checks and returns the original attempt 1, even after later attempts exist.
Its current status may evolve; its job/release identity cannot change. List views
show the latest attempt instead. Runtime/compiler/Godot/toolchain/image/package
identities are pinned on release creation and remain immutable.

Accepted retry keys likewise resolve their original attempt before archive/config
checks. Fresh retries reject active/completed work, archived projects, published
artifact metadata or an unavailable/mismatched pinned builder. Retry and cancel
atomically persist their event/outbox/audit effects. Repeated cancellation adds no
duplicate event/message; cancellation remains available after archiving. A viewer
can inspect but cannot retry/cancel. Membership revocation denies subsequent reads.

One transaction creates release, initial queued job/event, compact ID-only outbox
message and safe audit record. Storage failure rolls back all records and returns
a generic retryable503. No source, engine log or raw driver parameters enter the
response. Outbox topic `narrative.release_queued`, aggregate `narrative_release_job`,
payload `{schema_version:"1", tenant_id, release_id, job_id}`. A narrative relay is
still pending; existing ingestion filters do not consume this topic.

Admission locks the workspace row with PostgreSQL `FOR NO KEY UPDATE`, then the
project. It serializes admission counting while remaining compatible with audit
FK `KEY SHARE` from an existing project writer. `FOR UPDATE` here was shown to
deadlock a concurrent save/archive and is deliberately avoided. Count queued and
running jobs across the workspace. Replays precede the active-job cap. Lists use
the stored timestamp in SQL for cursor comparisons, avoiding SQLite timestamp
round-trip duplicates.

## Persistence and pending publication boundary

Four scoped tables reserve the final subsystem shape: immutable release identity,
mutable attempts, append-only events and immutable artifact metadata. Composite FKs
bind release->revision and job/event/artifact ownership to the exact project/tenant.
An active-job partial unique index permits only one queued/running job per release.
Status/fence constraints permit a token only on a running attempt; completed jobs
cannot have cancellation requested. PostgreSQL triggers forbid update/delete of
release identity, events and artifact metadata. Actual migration constraints and
immutable release updates were qualified against owned PostgreSQL.

The pure attempt transition boundary fences stale execution and cleanup, honors
cancellation before publication and revokes terminal tokens. Claim and failure/
cancellation persistence plus private immutable input loading are now implemented
under release -> job locks and qualified against actual PostgreSQL recovery writers.
Same-token/terminal/old-attempt replay cannot acquire; stale cleanup is a no-op.
Input loading checks current ownership/cancel before exact builder identity and
canonical revision/release hashes. Claim precedes builder resolution so an
unavailable builder can fail owned work. These services never launch a child or
authorize artifact insertion. Completion remains reserved for publication. Actual relay/
Temporal workflow, credential-free child runner, bounded object publication,
authorized downloads and Releases UI remain unimplemented. No artifact is published
or available for download by this initial slice.

See the [initial ledger report](../reports/2026-10-30-narrative-release-ledger.md)
and [lifecycle qualification](../reports/2026-10-30-narrative-release-lifecycle.md).

## Implemented artifact codec, pending runner integration

The standalone USTAR decoder/ZIP encoder now enforce fixed inventories, checked
headers/trailers, portable paths and count/per-file/aggregate/wire/output budgets.
No host extraction or filesystem discovery occurs. Short reads use a bounded
accumulator; ZIP file/parent and case collisions are rejected. Stream deadlines
and process termination belong to the still-pending runner. A real nonroot,
read-only, network-none tmpfs transport fixture passed; it is not an engine or
artifact publication claim. See the [codec report](../reports/2026-10-30-narrative-release-codec.md).

The explicitly prepared Linux image and standalone trusted child are now qualified
against actual Godot: fixed input copying, image-owned runtime hashes, closed
manifest parsing, bounded nonblocking engine diagnostics/deadlines, fixed web
inventory/USTAR and an independent180-second PID1 watchdog. A changed script with
an updated manifest was rejected; absent-supervisor watchdog exit124 was observed.
The credentialed host runner, fencing and publication remain pending. See the
[child report](../reports/2026-10-30-narrative-build-child.md) and
[preparation runbook](../runbooks/narrative-builder-preparation.md).

See the [execution ownership report](../reports/2026-10-30-narrative-release-execution.md)
for exact service/database verification and the remaining host-worker boundary.

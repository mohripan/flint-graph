# Narrative release control plane

M31 #124, implemented ledger/runner/publication/Temporal activity boundaries,
migrations `0018_narrative_releases` and `0019_narrative_workflow_owner`.
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
These settings admit durable queue intent; a separately started narrative relay
and worker are required to execute it. Ordinary API startup never invokes Docker
or downloads a toolchain. Missing configuration rejects new requests with503.
The connected worker and separate operator processes/periodic recovery are
qualified, and the Studio Releases dialog is the user-facing client. See the
[worker/relay runbook](../runbooks/narrative-build-worker.md) and the
[Releases UI report](../reports/2026-10-30-narrative-releases-ui.md).

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
payload `{schema_version:"1", tenant_id, release_id, job_id}`. The separate narrative
relay consumes only its two narrative topics; ingestion filters are unchanged.

Admission locks the workspace row with PostgreSQL `FOR NO KEY UPDATE`, then the
project. It serializes admission counting while remaining compatible with audit
FK `KEY SHARE` from an existing project writer. `FOR UPDATE` here was shown to
deadlock a concurrent save/archive and is deliberately avoided. Count queued and
running jobs across the workspace. Replays precede the active-job cap. Lists use
the stored timestamp in SQL for cursor comparisons, avoiding SQLite timestamp
round-trip duplicates.

## Persistence

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
authorize artifact insertion. Completion remains reserved for publication. Bounded
immutable publication and downloads have real engine/store/HTTP qualification;
the separate relay/workflow/activities now also have a connected native proof.
Operator processes and periodic recovery/sweeps now have actual process-loss and
natural-expiry proof. See the
[recovery report](../reports/2026-10-30-narrative-build-recovery.md).
Releases UI/browser acceptance passed; see the
[Releases UI report](../reports/2026-10-30-narrative-releases-ui.md).

See the [initial ledger report](../reports/2026-10-30-narrative-release-ledger.md)
and [lifecycle qualification](../reports/2026-10-30-narrative-release-lifecycle.md).

## Implemented artifact codec and standalone runner

The standalone USTAR decoder/ZIP encoder now enforce fixed inventories, checked
headers/trailers, portable paths and count/per-file/aggregate/wire/output budgets.
No host extraction or filesystem discovery occurs. Short reads use a bounded
accumulator; ZIP file/parent and case collisions are rejected. The host runner
now adds stream deadlines, process joining and owned cleanup. A real nonroot,
read-only, network-none tmpfs transport fixture passed; it is not an engine or
artifact publication claim. See the [codec report](../reports/2026-10-30-narrative-release-codec.md).

The explicitly prepared Linux image and standalone trusted child are now qualified
against actual Godot: fixed input copying, image-owned runtime hashes, closed
manifest parsing, bounded nonblocking engine diagnostics/deadlines, fixed web
inventory/USTAR and an independent180-second PID1 watchdog. A changed script with
an updated manifest was rejected; absent-supervisor watchdog exit124 was observed.
Standalone host execution, worker activity integration and publication are also
qualified with the separate scopes above. See the
[child report](../reports/2026-10-30-narrative-build-child.md) and
[preparation runbook](../runbooks/narrative-builder-preparation.md).

See the [execution ownership report](../reports/2026-10-30-narrative-release-execution.md)
for exact service/database verification and the remaining host-worker boundary.

The host adapter verifies pinned/effective image and container profiles before
engine start, captures/validates exact source and child output inventories, checks
ownership/cancellation between stages, adds external web licenses/notices and
returns private ZIP bytes. Repeated-cancel-safe finalization joins subprocesses/
decoder and removes only label-verified immutable container IDs plus token-marked
scratch. Unconfirmed cleanup retains a safe marker for future owned recovery.
Actual export and task cancellation passed. See the
[runner report](../reports/2026-10-30-narrative-build-runner.md).

The child's only writable paths are two bounded tmpfs mounts:
`/scratch` (256 MiB) and `/tmp` (16 MiB), both mode 1777. The host requires
exactly this map in the effective configuration. Godot's Linux export stages
`project.binary` under the fixed `/tmp`, ignoring `TMPDIR`. With a read-only
`/tmp`, it logs an error, exits 0 and packs an empty settings entry that browsers
cannot boot.

The host therefore also requires the exported Godot 4.7 pack (format 4,
unencrypted) to carry a non-empty `project.binary` starting with `ECFG` before
producing artifacts. Otherwise it fails closed with `artifact_invalid`. Releases
published before this check have unbootable browser builds; a new release of
the same revision replaces them.

## Implemented immutable publication and authorized attachments

The release-specific store adapter uses conditional create-only writes and exact
size/actual-byte/hash checks with closed bodies and safe SDK errors. Publication
rechecks active ownership/cancel under release -> job locks, validates three
server-derived receipts/caps and the canonical DB-bound manifest, and commits all
artifact metadata/status/event atomically. Completed replay returns stable IDs;
stale/rolled-back/cancelled work exposes no partial artifacts.

Viewer-authorized attachment downloads check complete same-job/same-fence metadata
and project/tenant/archive access before bounded store reads. Verified bytes use
safe filenames/private-no-store/nosniff; failed storage/integrity is a safe503.
Item GET supplies artifact metadata; list/acceptance responses remain summaries.
See [publication qualification](../reports/2026-10-30-narrative-release-publication.md)
and the [artifact runbook](../runbooks/narrative-release-artifacts.md). Source, keys
and ZIPs remain activity-local, never workflow payloads or ordinary telemetry.

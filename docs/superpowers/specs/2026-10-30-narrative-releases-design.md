# Immutable narrative releases and isolated build jobs

Scope: M31 #124 after #122/#123. Proceed under the user's standing authorization
for autonomous issue-by-issue implementation and the existing one review agent.
This is an architectural subsystem with a focused design and tests before code.
No paid models, arbitrary creator scripts, asset intake or hosted public game
publishing is included. Text revisions and local studio playtests remain usable
when release infrastructure is disabled.

## Outcome and alternatives

An author selects a saved revision, requests a release and can leave/reload. The
durable job eventually offers an editable Godot source ZIP, browser-build ZIP and
release manifest through authorized downloads. Every artifact is tied to that
revision/package and a fixed trusted runtime/toolchain. Failed/cancelled jobs never
expose a partial release. Downloading always creates files under the user's chosen
local destination; the application never reads back or overwrites customized exports.

Use PostgreSQL plus the existing transactional outbox/Temporal infrastructure,
with object storage for private immutable bytes. Synchronous API compilation would
block requests and lose work on interruption. A second in-process queue would add
recovery semantics already provided by Temporal. Passing source or ZIPs in workflow
history would unnecessarily duplicate private text and large payloads; send IDs only.

Build children run a fixed trusted image without network or credentials. The
credentialed host activity prepares validated data and uploads/verifies artifacts;
the engine child cannot access PostgreSQL, Temporal, object storage, providers,
the Docker socket or unrelated host files. Docker daemon access belongs to this
explicitly enabled trusted worker, never the API or engine child. This local
container boundary requires real qualification; it is not a hostile multi-tenant
arbitrary-code execution service or a substitute for later microVM isolation.

## Release identity and ledger

Migration 0018 adds separate tables rather than overloading ingestion jobs:

- `narrative_releases`: immutable identity containing UUID, tenant/project/revision,
  creator, idempotency key/request hash, package hash, compiler/runtime/toolchain
  identity, trusted image digest and creation time. Composite FK scopes the exact
  immutable revision to project/workspace. One accepted request creates one release.
- `narrative_release_jobs`: mutable attempt state referencing one release, with
  monotonically increasing attempt number, queued/running/completed/failed/cancelled,
  cancellation flag, current execution fence token, timestamps and safe error code.
  A release has one active attempt at most; retries of failed/cancelled jobs create
  a new attempt with a caller key. Replaying a key returns that same attempt.
- `narrative_release_events`: monotonic per-job sequence, operation code and compact
  safe IDs/status only. No source, raw engine logs, credentials or signed URLs.
- `narrative_release_artifacts`: immutable metadata for exactly the successful
  publication attempt: source ZIP, web ZIP, manifest JSON. Record tenant/release/job,
  server-derived private object key, SHA-256, size, media type and safe filename.
  Unique kind per release; no published-object mutation. Composite FKs enforce
  ownership. Use PostgreSQL immutability triggers for release identity/artifacts,
  with SQLite/API tests plus actual migration/constraint qualification.

Release identity remains immutable while the job changes. A successful release
cannot be rebuilt in place; request a new release to use another runtime/toolchain.
An explicit older/conflict revision is allowed because it is a validated immutable
snapshot; the UI identifies its number/conflict status before requesting release.
Project head changes never change an already-queued source.

Release keys are unique within project/workspace; retry keys are unique within a
release. Request hashes compare explicit caller intent (revision ID for creation,
release ID for retry), independently of current builder configuration. Same key
with different caller intent returns 409. Resolve an authorized same-key replay
before current archived/configuration/availability/admission checks: disabling or
upgrading the builder must not prevent recovery of an already accepted response.
New requests select the configured trusted runtime once; retries keep the original
release's runtime and never select a newer one implicitly.

Initial bounds: 10 active queued/running jobs per workspace, bounded metadata
pagination and 1 engine child per worker process. These are operational limits,
not billing or cluster-wide fair scheduling. Enforce the workspace admission limit
under a row lock so concurrent API requests cannot exceed it. A same-key replay
precedes admission counting and returns its existing result without new work.

## API and authorization

Add routes under `/v1/narrative/projects/{project_id}/releases`:

| Endpoint | Contract |
| --- | --- |
| POST collection | Member+, `{revision_id, idempotency_key}`; 202 release/job identity |
| GET collection/item | Viewer+, compact metadata and job status; bounded cursor |
| GET `/{release_id}/jobs` and `/{release_id}/jobs/{job_id}` | Scoped attempts/events metadata |
| POST `/{release_id}/retry` | Member+, `{idempotency_key}`; only terminal failed/cancelled, no successful publication |
| POST `/{release_id}/jobs/{job_id}/cancel` | Member+, idempotent cancellation request; never converts completed to cancelled |
| GET `/{release_id}/artifacts/{kind}` | Viewer+, completed publication only; verified bytes with attachment filename |

Reuse server membership authorization and narrative request/rate boundary. Foreign
project/revision/release/job/artifact IDs and cursors return 404 after workspace
authorization. Never treat a request header as authentication. Archived projects
reject new release/retry actions; existing metadata/download reads require explicit
`include_archived=true`, matching #122. Cancellation remains allowed to stop queued
or running work. Re-check membership on every download; do not give the browser a
long-lived public or presigned object-store URL. Keep storage keys/internal paths
out of public responses. Missing/incomplete/tampered objects fail closed with a
safe code; no source-bearing exception details in responses or ordinary logs.

Downloads return bounded verified bytes with `Content-Disposition: attachment`,
`Cache-Control: private, no-store`, safe ASCII filenames and `nosniff`. Initial ZIP
cap 64 MiB each, manifest cap 1 MiB, total publication cap 128 MiB. The API verifies
HEAD size and bounded read/hash before responding; it must not trust HEAD alone or
the existing unbounded `get_bytes`. Add a separate bounded read/immutable put seam
without weakening current ingestion behavior. No HTML is served as application
origin content; the web artifact is an attachment, not an inline preview route.

Release configuration is opt-in. Ordinary API/startup never pulls an image,
downloads Godot or launches Docker. Missing explicit build configuration returns
a clear unavailable response on new release requests; manual authoring still works.

## Durable dispatch, retries and cancellation

Creating release/job/initial event/`narrative.release_queued` outbox occurs in one
transaction. Payloads contain job/release/workspace IDs and schema version only.
The immutable revision is loaded and validated in an activity, not copied through
Temporal input, results, heartbeat details or workflow memo. The existing ingestion
topic filters remain unchanged. Add an explicit narrative relay using the same
outbox ledger and Temporal duplicate-safe start policies, with start messages
prioritized before cancellation messages. Workflow ID is `narrative-release-{job_id}`
and task queue is a separate configured narrative-build queue.

The workflow calls a heartbeating build activity and compact transition activities.
Build activity timeout 5 minutes, heartbeat 10 seconds, at most 3 transient attempts;
input/schema/hash/toolchain failures are nonretryable safe codes. Each actual engine
execution receives a fresh fence token stored under the job lock. Re-execution
invalidates the prior fence, so an old worker cannot publish after retry/recovery.
Use token-specific scratch/container/object namespaces. A per-child watchdog stops
execution at 180 seconds even if the activity worker disappears; a startup sweep
only handles verifiably owned expired containers/scratch state, not arbitrary Docker
resources. Bound diagnostic output while draining it; do not buffer unbounded logs.

Cancellation commits flag/event/outbox before return. The activity heartbeats and
checks cancellation at stage boundaries and before publication; on cancellation it
stops only its owned child and records safe cleanup. Workflow cancellation uses
shielded final state cleanup as required by the SDK and re-raises cancellation.
The publication transaction locks the job and rejects cancelled/stale fences. That
lock is the linearization point: if completion committed first, cancellation reports
completed; if cancellation committed first, publication is forbidden.

Use a consistent lock order: workspace/project when admission requires them, then
release, then job. Publication, explicit retry and terminal transitions serialize
under release -> job locks. Publication requires the job to be the active running
attempt and its execution fence to match. Every failure/cancel cleanup also compares
the owning token and active attempt, so stale cleanup cannot fail a replacement
execution. Any terminal transition revokes the fence. A failed old job cannot
publish after explicit retry created a new job; completed publication cannot be
changed by late activity failure or cancellation cleanup. Record these exact races
in the transition and PostgreSQL tests.

Claiming ownership is separate from resolving the pinned engine: commit the fresh
fence first, then recheck active ownership/cancellation before private source and
builder resolution. This lets an unavailable builder terminate the owned attempt
as `runtime_unavailable` instead of stranding accepted work in queued state.
Cancellation recovery works even if the original image was removed. Same-token
claim replay is a no-op and never authorizes another child. The private source
loader returns only activity-local captured bytes; never pass its result through
Temporal input/results/heartbeats. Drop release/job locks before any engine work.

If the worker dies after uploading, private orphan objects remain inaccessible.
If it dies after atomic publication but before activity acknowledgement, replay
returns the already-published metadata without rebuilding or overwriting. Automatic
activity retries stay within the same job; explicit user retry creates a new job.
Do not reuse a cancelled/failed workflow ID for a new user attempt.

## Trusted input, engine child and artifact publication

The host reads the tenant-scoped immutable revision, strict-validates with
`load_text_package`, checks the recorded package hash and exports only the trusted
M30 `TEMPLATE_FILES` into a new owned directory. No creator-supplied project tree,
script, plugin, import configuration, URL, shell argument or archive is accepted.
Store the runtime/compiler/toolchain/image identities on the release request and
require an exact match at execution; no silent runtime upgrade on queued work.

Build image preparation is an explicit operator tool: verify official Godot 4.7.2
Linux binary and single-threaded web templates against pinned checksums, pin base
image by immutable digest, and record final image ID/manifest. Runtime compilation
uses `--pull=never`; ordinary jobs have no installation/network fallback. Extend
the toolchain metadata without changing the qualified Windows source-export path.

For each child, use a fixed command/argument vector, network `none`, nonroot UID,
read-only root filesystem, dropped capabilities, no-new-privileges, default seccomp,
2 CPUs, 1 GiB memory with equal swap cap, 128 PIDs, bounded tmpfs scratch and no
devices/socket/host-network mounts. Only a read-only exact input package is mounted.
Copy into child scratch for Godot's imports; write outputs inside bounded scratch,
then retrieve only the fixed output files. Do not allow a writable host bind as an
unbounded engine output volume. Prove effective limits rather than only argv flags.

Bound retrieval before host extraction/allocation: no blind `docker cp` directory
extraction or `extractall`. Read a capped archive/file stream, validate normalized
names, entry count/type, declared and actual sizes and total bytes, then write only
allowlisted regular files into a fresh owned host directory. Reject links, sparse
entries, traversal, duplicates and unexpected files. On overflow/error, stop the
owned retrieval process/container and clean up only that execution's state. An
inventory check after extraction is insufficient to enforce this boundary.

Transport qualification found that Docker's archive-copy endpoint cannot see the
bounded tmpfs output mount. Use a fixed trusted in-child archiver through `docker
exec`, with USTAR output and a fixed flat web inventory; no creator command/path
selection or host-side shell extraction. A real nonroot, read-only, network-none
fixture produced the expected directory/regular-file headers. The host codec reads
one checked512-byte header at a time (standard-library `TarInfo.frombuf`, without
automatic PAX/longname processing), rejects extended/link/sparse/special entries
before payload reads, caps per-file/aggregate/wire bytes and checks zero padding/
trailer plus exact inventory. It returns bounded byte mappings; no archive metadata
is extracted into host paths. Given-file ZIP output uses fixed ordering/timestamps
and regular0644 modes. Deadline/process cleanup remains the runner's responsibility.

Generate ZIPs with deterministic entry order, fixed timestamps and safe normalized
relative paths, without symlinks/junctions/traversal/duplicate names or `.godot`
import caches. The source project keeps trusted editable scripts, exact canonical
story/notices/assets-empty manifest, licenses and pinned export instructions.
Browser ZIP contains only qualified generated web files/notices, never host paths,
tokens or diagnostic logs. ZIP byte reproducibility across engine hosts is not
assumed; record actual output SHA-256 and promise package/route identity.

The host validates output inventory/types/size/hashes, independently verifies source
manifest/package identity and produces a release manifest binding revision/package,
runtime/toolchain/image and source/web ZIP hashes. Upload to server-derived keys
under tenant/release/job/fence. Conditional immutable put (`If-None-Match: *`) must
be actually supported by the configured S3-compatible store; existing objects are
accepted only after exact size/hash verification. Conflict/different bytes fail
closed. Verify uploaded objects before the final PostgreSQL publication transaction
inserts all artifact rows, completed event and job status atomically. No artifact
row/download is visible before every output has been checked.

S3 and PostgreSQL do not share a transaction. Orphan outputs are private and do not
count as releases. Retention cleanup must only remove unreferenced old attempts
after checking authoritative publication references; broad bucket deletion is not
part of this delivery. Missing published objects surface as an operational error,
never a silent successful rebuild under the same release identity.

## UI, tests and qualification

Add a Releases panel with explicit saved-revision selection, pending/running status,
safe failures, cancel/retry and authorized attachment downloads. Reload reads server
state; no frontend transcript/source bundle is sent to Temporal. Keep editor draft
and release status independent. API errors use the existing access-loss cleanup.
Downloads do not start automatically from a model output or background job completion.

Implement in slices: ledger/API admission/retry/cancel + outbox; trusted runner and
bounded artifact codec; immutable object publication/download; Temporal activity/
relay integration; UI and complete live release/restart proof. Each slice gets
tests before changed behavior at these public seams. Reuse the one review agent.

Offline tests cover scoped roles/cursors/base IDs, idempotency/body mismatch,
admission races, state/fence transitions, cancel/publication ordering, immutable
metadata/FKs, ZIP traversal/size/inventory, bounded object reads and immutable-put
conflicts. Deterministic test doubles cover transport faults, not engine execution
claims. Actual PostgreSQL constraints and queued writers must also be checked.

Owned live qualification requires Temporal + object store + PostgreSQL + pinned
Linux Godot image. Request release through HTTP/browser, kill/restart only owned
relay/worker around dispatch/upload/publication boundaries, cancel a running child,
retry failure and verify one complete artifact set with no cancelled publication.
Inspect the real child network/env/mounts/limits and synthetic secret canaries; no
private documents or provider credentials are used. Prove conditional put against
the actual object store. Download under two workspaces/revoked membership; verify
hashes, import downloaded source in the actual engine and follow equivalent routes
in its browser build and #123 saved-revision preview. Record screenshots and exact
passed/skipped commands. Missing engine/container/store access is an explicit block
to the relevant acceptance, not permission to claim mock-only completion.

## Primary references reviewed 2026-10-30

- [S3 PutObject conditional writes](https://docs.aws.amazon.com/AmazonS3/latest/API/API_PutObject.html):
  create-only preconditions and conflict semantics; MinIO compatibility needs proof.
- [Docker run options](https://docs.docker.com/reference/cli/docker/container/run/)
  and [resource constraints](https://docs.docker.com/engine/containers/resource_constraints/):
  configure and inspect the explicit child boundary.
- [Docker copy corner cases](https://docs.docker.com/reference/cli/docker/container/cp/):
  tmpfs requires the explicit child-archive transport rather than filesystem copy.
- [Temporal Python cancellation](https://docs.temporal.io/develop/python/workflows/cancellation):
  heartbeat delivery, cleanup and re-raising cancellation.

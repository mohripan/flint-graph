# ADR0037: Temporal-owned narrative build attempts

Status: accepted for implementation under #124 and the user's autonomous delivery
authorization,2026-10-30. Focused continuation of the immutable release design;
automatic dispatch remains unimplemented at this decision checkpoint.

## Context

Fresh execution tokens already fence publication and old cleanup. The actual
Godot/MinIO/HTTP path is qualified. Connecting Temporal introduces two additional
failure windows: an older timed-out activity can arrive late at its first claim,
and a final worker crash can leave no live activity to finalize a running job.
Blindly reading the current token in arbitrary cleanup would let old cleanup
steal a replacement's ownership. Passing source or ZIPs in workflow history is
also unnecessary and prohibited by the existing release contract.

## Decision

Keep a separate opt-in narrative relay, workflow, activity worker and task queue.
Preserve ingestion topic filters. Relay starts use the fixed per-job workflow ID,
use-existing conflict handling and reject-duplicate reuse; explicit user retry is
a new job/workflow ID. Starts precede cancellation dispatch. Payloads/memo/results/
heartbeats contain compact IDs/status only, never source, ZIPs, keys or raw errors.

Migration0019 adds nullable workflow-run UUID and activity-attempt number to each
release job, constrained as an absent pair or a valid pair. Existing/manual
qualified attempts remain readable with both absent. The first Temporal claim
binds a job to one run. Same-run newer/equal activity attempts may acquire fresh
execution tokens; lower attempts, a different run or an unowned manual claim may
not take over that bound job. Ordinary activity cleanup still requires its exact
original token. Terminal state revokes that token and retains owner identity for
inspection; no new public DTO exposes it.

Workflow execution retry/continue-as-new/reset into another run for the same job
is unsupported in this first delivery. Recovery uses activity retries within the
same run; explicit failed/cancelled user retry creates a new job. Operators must
not reset an active narrative workflow to bypass PostgreSQL ownership. A stale
different-run workflow returns no-op state and cannot steal the existing owner.

One heartbeating activity performs claim/commit, cancellation check, private input
validation, bounded host runner, immutable uploads and atomic publication. Each
actual activity execution has a new token and supplies SDK run/attempt identity.
No DB locks span engine/network work. Per-worker activity concurrency is one;
stage checks heartbeat and read current fence/cancellation. The qualified child
watchdog remains independent of worker liveness. Builder/input/integrity errors
are safe terminal failures; transient infrastructure failures may retry at most
three times. Retries never reuse prior execution scratch/object namespaces.

The workflow supervises exhaustion/cancellation with a distinct finalization
activity. Its authority is the persisted matching workflow-run identity and latest
user attempt, not a guessed execution token. After the build activity's terminal
server outcome, it locks release/job, verifies that run still owns the job, then
fenced-finalizes only that run's current execution. It never changes a completed
publication or a new user attempt. Arbitrary old build-activity cleanup cannot use
this supervisor operation. A startup recovery check may use the same authority
only after observing that exact persisted Temporal run as closed; running/unknown
runs and absent ownership fail safe.

Cancellation asks Temporal to stop activity work and shields bounded owned cleanup.
API cancellation already commits the PostgreSQL flag first, so upload/late worker
completion cannot publish. Cancellation finalization must work with an unavailable
original image. Repeated cancellation must not abandon subprocess/decoder handles.

Startup sweeps inspect only explicitly managed, expired containers/scratch with
verifiable ownership; stop by immutable container ID. Never sweep arbitrary Docker
resources, user exports, ingestion jobs or #109 trace-probe state. Retained private
orphans remain inaccessible until separately qualified retention.

## Alternatives and limits

UUID fences alone handle late completion but cannot order late first claims.
Generic cleanup that reads any current token erases ownership. Retrying the whole
workflow/new run silently would require another ordering/admission protocol;
explicit new user attempts give a clear identity instead. A synchronous API or
second in-process queue loses durable dispatch/recovery already supplied by
Temporal. Putting private text/artifacts in Temporal is rejected.

This does not guarantee exactly-once engine computation; worker/heartbeat failures
can leave briefly overlapping credential-free children until their guards/watchdog
or owned sweep stops them. Publication remains at most one complete artifact set.
Object storage and PostgreSQL still have no shared transaction. Production Temporal
authentication/HA and stronger hostile-code isolation remain separate platform work.

## Verification required before closing #124

Add tests before behavior: owner pair constraints, old-attempt/run/manual claim
rejection, same-run recovery, supervisor ownership and cancellation/completion
ordering. Qualify actual PostgreSQL and native Temporal dispatch duplicates,
worker interruption/exhaustion, running cancellation and private-payload absence.
Inspect real child limits and publication/download hashes. Then deliver the
server-backed Releases UI and real browser export/play proof. Missing services
cannot be replaced by a mock-only completion claim.

Primary APIs inspected: installed Temporal Python activity Info (workflow_run_id,
attempt), workflow activity cancellation modes and existing project retry/outbox
implementations. Use the installed SDK plus official Temporal docs when implementing
cancellation/retry details; no older ingestion behavior is changed by this decision.

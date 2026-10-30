# Narrative build worker and relay

This is the model-free, opt-in narrative build path. It does not run ingestion or
serve a public API. The trusted worker host needs Docker CLI/daemon access; API
hosts do not. Prepare the pinned Linux image explicitly with the
[builder preparation runbook](narrative-builder-preparation.md). Startup never
pulls images, provisions templates or downloads models.

## Configuration and start

Use the intended database, private object bucket and Temporal address/namespace
in both process environments. Apply migrations through 0019 first. Keep the task
queue and absolute private work root stable across restarts. The queue must differ
from `FLINT_GRAPH_TEMPORAL_TASK_QUEUE` used by ingestion.

Worker settings:

- `FLINT_GRAPH_NARRATIVE_WORKER_ENABLED=true` (default false).
- `FLINT_GRAPH_NARRATIVE_TASK_QUEUE=narrative-build` (default; relay must match).
- `FLINT_GRAPH_NARRATIVE_BUILD_WORK_ROOT`: existing absolute resolved private
  directory, separate from creator exports. The worker creates token-marked child
  directories inside it. Preserve this root through restarts.
- `FLINT_GRAPH_NARRATIVE_RELEASE_BUILDER_IMAGE_DIGEST`: exact prepared `sha256:`
  image identity; `FLINT_GRAPH_NARRATIVE_RELEASE_TOOLCHAIN_SHA256`: prepared receipt.
- `FLINT_GRAPH_NARRATIVE_RECOVERY_INTERVAL_SECONDS`: 30 by default, 5–3600 allowed.

Each build child runs read-only and network-none, with exactly two bounded tmpfs
mounts: `/scratch` (256 MiB) and `/tmp` (16 MiB). Godot's Linux export needs a
writable `/tmp` to stage `project.binary`. Without it, the export still exits 0
but produces an unbootable browser build. The worker rejects any other effective
mount profile, and any Web pack without readable project settings
(`artifact_invalid`). Restart workers after upgrading so they load this profile.

Run `uv run python -m flint_graph.processes.narrative_worker`. One activity executes
per worker; it can receive workflow tasks while independent maintenance loops
inspect closed runs and expired owned scratch. Shutdown gives activities 30 seconds
to drain; a hard crash is handled through SDK activity retries and the independent
child watchdog. An old timed-out activity cannot cancel or publish over its retry.

In a separate process enable `FLINT_GRAPH_NARRATIVE_RELAY_ENABLED=true` and run
`uv run python -m flint_graph.processes.narrative_relay`. Poll interval defaults to
1 second (`FLINT_GRAPH_NARRATIVE_RELAY_POLL_INTERVAL_SECONDS`, 0.1–60), batch size 10
(`FLINT_GRAPH_NARRATIVE_RELAY_BATCH_SIZE`, 1–100). Each accepted-run registration and
outbox acknowledgement commits before the next message's RPC. The relay only
consumes `narrative.release_queued` / `narrative.release_cancelled`.

The API independently controls admission using `FLINT_GRAPH_NARRATIVE_RELEASES_ENABLED`
and the same captured image/toolchain pins. It can stop admitting new work while
workers drain existing jobs. API admission does not launch a worker. Existing
OIDC/deployment settings continue to apply; do not change them to start these roles.
Narrative builds require no answer/extraction/embedding provider. For an isolated
local role without provider credentials explicitly select the four deterministic
provider settings, as in the qualified owned fixtures. That does not qualify
deterministic providers for the separate GraphRAG answer product.

## Recovery and inspection

PostgreSQL owns release state. A registered workflow run is checked against its
exact original ID/type/queue/input before recovery; a running, unknown, chained,
foreign or manual/unbound run is never adopted. A cursor advances past live or
unavailable runs. Per-pass inspection budget is 15 seconds with at most 10 seconds
for each run observation. Physical cleanup occurs outside DB locks; finalization
compares the same run/attempt/token/latest-job snapshot. Cancellation flags win
over failed completion; successful publication cannot be rewritten.

Scratch carries `.owner` and a bounded canonical `.execution.json` receipt, with
an expiry240 seconds after preparation (the independent child watchdog is 180
seconds). Sweeps retain streaming scan progress across calls, examine at most 1000
entries, queue at most 5 expired candidates and attempt at most 5 cleanups. A 15-second
between-operation budget and first-error backoff bound each pass; one shielded
cleanup can exceed that soft budget by its bounded CLI cleanup time. Sweeps and
DB recovery run independently, so a Docker outage does not serialize them.

Only exact resolved token-marked scratch with regular bounded ownership metadata
is eligible. Container removal verifies exact name, immutable ID, execution label,
image and expiry. Unknown/legacy/unexpired entries and creator-export siblings are
retained. Cleanup needs no original image lookup. Private unpublished object-store
orphans have no public URLs and remain outside this scratch sweep; broader object
retention is still separate work.

Do not reset/continue/retry a workflow into a new run under the same job ID. The
current protocol supports activity retries within one run. Use the authorized
release retry API for a new user attempt after failed/cancelled work. Changing a
release's captured compiler/image/toolchain is not a retry operation.

Use the Studio **Releases** dialog or API release/job/events to inspect safe public
state, and Temporal task-queue pollers to check worker presence. Logs use fixed
codes/counts, never private source or driver errors. See the
[actual process-loss, cancel/retry and cleanup report](../reports/2026-10-30-narrative-build-recovery.md).

Releases published before the `/tmp` mount and pack check have unbootable browser
builds; their source ZIPs are unaffected. Published releases are immutable, so
request a new release of the same saved revision. See the
[Releases UI report](../reports/2026-10-30-narrative-releases-ui.md).

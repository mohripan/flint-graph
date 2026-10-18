# ADR 0033: Local app-only telemetry switches preserve each process snapshot

Date: 2026-10-18. Status: accepted for the standard local Compose deployment.
Milestone 24 / #108, prerequisite to #107; also improves milestone 26 DX.

## Decision

Add `flint-graph-telemetry --mode base|phoenix|jaeger|combined`. Default operation
is read-only preview. `--apply` is explicit and recreates only ingestion-worker,
relay, cleanup and then API. Telemetry tools must already run the selected
configuration; this command never starts/reconfigures backends or data services.

The API and worker can legitimately run different image/model snapshots. Capture
each container's immutable image ID, full environment, process command,
entrypoint, working directory and user in memory. Override only its OTLP endpoint.
Render the proposed Compose configuration for all four first and reject new
environment defaults or process drift before any recreation. Escape literal
dollars in all JSON string values before Compose interpolation, then undo the
canonical renderer's one-layer dollar re-escaping for the preflight comparison.
Native config plus a network-isolated disposable runtime probe verify literal
dollars/equal signs against an independently encoded oracle. Recreate without
dependencies, builds or pulls; then compare each process's image/environment and
process configuration. Recheck container IDs before rollout and each recreation
to detect concurrent operator replacements. This is not an atomic deployment
transaction or distributed lock: avoid concurrent configuration changes.

The helper refuses remote Docker endpoints, non-local app environments, wrong
project/root ownership, stopped/paused/missing/replicated services, disabled
tracing, unsupported custom mounts, port/network/resource/security/restart
settings, unhealthy selected backends, and mismatched gateway mode. It targets
the fixed standard `flint-graph` Compose project, not an arbitrary cluster
deployment. Unix-socket and local Windows named-pipe Docker connections are
accepted; Linux/custom profiles adding extra hosts or other guarded settings
need explicit future support rather than silently dropping them.

Docker inspection and Compose rendering can contain credentials. Keep them in
memory, pass overrides by subprocess stdin, do not use a shell or generated
environment files, and never echo Docker output/errors. Reports contain only
mode, service names, fixed endpoint, success booleans or a failure phase and
completed-service list. This does not eliminate Docker daemon administrators'
access to container environments or guarantee host-process memory secrecy.

Switching is sequential and may briefly interrupt API requests. Do not claim
atomic rollback. On failure, stop, inspect which services changed, prepare the
prior telemetry backend mode and explicitly preview/apply it. Returning to base
preserves **current** per-process non-telemetry settings, not a persisted earlier
snapshot. A concurrent external model change is not undone or guessed. Startup
process/health checks are not proof of end-to-end telemetry delivery; run the
gateway/correlation checks separately.

## Alternatives and boundaries

Ambient Compose variables risk resetting model/provider/dimension settings and
replacing intentionally different process images. Saving whole environments to
an overlay/backup file increases credential exposure and recovery ambiguity.
Rebuilding all services also broadens a telemetry-only change unnecessarily.
The in-memory app-only override keeps this step narrow and inspectable.

Public CLI/Docker-boundary tests cover preview, all fixed modes, immutable
images, differing model settings, literal dollar/equal signs, environment drift,
unsupported host configuration, concurrent replacements, partial failures and
remote-context rejection. The explicit live rehearsal switches base to combined,
restarts owned processes, rolls back to base, compares every environment value
without printing it, and verifies public readiness plus unchanged data-container
identities. See the [runbook](../runbooks/local-telemetry-switch.md) and
[report](../reports/2026-10-18-local-telemetry-switch.md).

This delivers #108, not full #107/#72 or production #43. It does not make
request-bound SSE durable, change models/indexes, prove arbitrary agent safety,
drain in-flight ingestion, or certify third-party telemetry privacy.

## Primary references

Reviewed 2026-10-18:
[Compose interpolation](https://docs.docker.com/reference/compose-file/interpolation/),
[config rendering](https://docs.docker.com/reference/cli/docker/compose/config/),
and the local **5.3.1** implementation's
[canonical dollar escaping](https://github.com/docker/compose/blob/v5.3.1/cmd/compose/config.go).
Native qualification caught the renderer behavior that an initially simplified
Docker mock missed; CI now checks real string preservation, not only the mock.

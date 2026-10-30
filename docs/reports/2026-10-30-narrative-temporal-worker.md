# Connected narrative Temporal worker qualification

M31 #124 remains open. Delivered: separate narrative outbox relay, exact-run SDK
adapter, deterministic workflow and SDK-authorized activities. No ingestion filter
or trace-probe work changed. Source, ZIPs, object keys, execution tokens and arbitrary
trace baggage stay out of workflow inputs/memo/results/heartbeats/safe failures.

## Implemented behavior

The relay validates the exact IDs-only outbox shape and matching tenant/job/
aggregate, starts the fixed workflow, and verifies its exact run/type/queue and
original-start input. Accepted run/attempt0 and outbox acknowledgement commit
together, before the next message's RPC. Closed lost-ACK replay reuses that same
verified run. Cancellation addresses the exact run. Poison messages get delayed
safe retry metadata; ingestion topics are never consumed.

One fixed build activity chain permits 3 attempts, a 5-minute execution timeout and
10-second heartbeat timeout. The workflow waits for server-terminal cancellation
before supervising; repeated cancellation cannot abandon finalization. All results
require exact keys, expected job and closed status. Malformed build results enter
safe supervision.

Activities check SDK namespace/queue/workflow ID/type/run and activity ID/type/
attempt, claim a fresh DB fence, load source privately, run Godot, verify immutable
uploads and atomically publish the complete set. Heartbeats and DB guards stop
stale/cancelled work. Only an actual SDK cancel request terminal-cancels: timeout,
not-found and shutdown preserve retry eligibility. Raw exceptions cannot cross the
activity edge. Finalization snapshots run/attempt/token, releases locks for exact
owned cleanup, then compares that snapshot before mutation. It needs no original
image lookup and cannot overwrite publication/newer user jobs/manual owners.

## Verification

Explicit isolated PostgreSQL, Temporal 1.32.0 namespace, real MinIO and pinned
Godot 4.7.2 Linux image only. No user volumes/corpus, paid provider, model download
or image pull. Image: `sha256:0e0ee5625ab13bd5a4ceade377487a88c78acc549db8261679ea36c0e7e18511`.

| Boundary | Result |
| --- | --- |
| Connected native worker | 2 passed / 2 explicit SQLite skips, 22.76s |
| Actual Temporal dispatch | 3 passed: duplicate/closed replay, exact cancellation, wrong input and baggage canary |
| Actual workflow policies plus compact contracts | 17 passed: bounded retries, malformed results, shielded repeated cancellation |
| SQLite/actual PostgreSQL relay | 10 passed, including lost DB ack and registration visible during blocked second RPC |
| SDK activity/SQLite/actual PostgreSQL | 14 passed: identity, registration race, unavailable toolchain and differentiated cancellation |

The connected success case queues before worker startup, uses the production
workflow/activities/relay with the actual engine/store/database, downloads all 3
artifacts through authorized ASGI HTTP APIs and verifies byte hashes, source
canary/web inventory and empty scratch. The canary exists in downloaded source and
is absent from actual workflow history. The second connected case injects failures
before the first claim for all 3 SDK attempts; production supervision fails the
registered attempt 0 safely. That failure case makes no engine-execution claim.
Policy activity probes are separate from real-engine qualification.

The sole reviewer checked all slices. Findings fixed: registration batch latency,
unchecked result dictionaries and generic cancellation incorrectly cancelling a
timed-out job. Native fixture schemas/known published keys are removed only by
their owning tests; the existing studio fixtures remain available.

Passed: `uv run ruff check .`, `uv run mypy` (192 source files), `uv lock --check`,
the deterministic acme-smoke `flint-graph-eval run`, test-configured
`alembic upgrade head --sql`, `docker compose config --quiet`, `git diff --check`.
The isolated public fixture DB actually upgraded 0018→0019 after fresh-schema tests.
Final `uv run pytest -q --tb=short`: **1383 passed,69 explicit skips,215.08s**.
The skips include native opt-in tests; their separate real-service runs are above.

## Remaining acceptance

Long-running operator worker/relay processes, periodic exact closed-run recovery,
expired owned child/scratch sweeps, process-kill/restart proof, Releases UI and the
complete browser release/play flow remain pending. Ordinary local API release
admission stays disabled. The connected proof uses a native test Worker; it is not
a deployment/process-loss recovery claim. Frontend source is unchanged.
See [M31 status](../milestones/31-authored-narrative-studio.md) for the delivery gate.

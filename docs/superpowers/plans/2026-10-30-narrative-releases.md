# M31 immutable releases implementation plan

Scope/authorization: #124, the [focused design](../specs/2026-10-30-narrative-releases-design.md),
and the user's autonomous continuation instruction. The existing review agent
identified fencing, configuration-independent replay and pre-extraction bounds;
the written design now pins these before implementation.

Progress2026-10-30: ledger/lifecycle, fenced execution/private input loading and
standalone codec/child/host-runner qualification are delivered. Reports under
`docs/reports/2026-10-30-narrative-*` distinguish actual PostgreSQL, native image
and fault proofs. Object publication/downloads, worker/activity/startup recovery,
The connected relay/workflow/activities are now native-qualified too; see the
Temporal worker report. Operator processes and periodic recovery/sweeps now have
actual process-loss/cancel/retry/natural-expiry qualification too; see the build
recovery report. The Releases UI and end-to-end author/build/download/play proof
are delivered too (step 5); see the Releases UI report, which also records the
empty-`project.binary` export fix.

1. Add public API/transition tests before implementation. Introduce migration 0018,
   scoped immutable release identity, jobs/events/artifacts and release admission,
   key/body replay, retry/cancel/read APIs. Queue initial/cancel outbox atomically.
   Keep downloads unavailable until atomic successful publication. Prove SQLite
   contracts plus actual owned PostgreSQL FKs/triggers/concurrency; no engine claim.
2. Add failing runner/artifact-codec tests. Build deterministic bounded ZIP codecs,
   bounded pre-extraction child transport and exact trusted input/output manifests.
   Explicitly provision/verify/pin the Linux Godot image outside runtime jobs.
   Qualify a real credential-free network-none bounded child with the original
   text-only fixture; retain source/output identities and effective container config.
3. Add immutable object-store/bounded read and publication/download seams, with
   object conflict/tamper/overflow/partial-upload tests. Prove create-only behavior
   against an owned real store and authorized downloads under signed membership.
   Test terminal/fence/cancel/retry races; no partial publication can be visible.
4. Add narrative relay/workflow/activities/processes and opt-in deployment settings.
   Pass compact IDs only, preserve ingestion topic behavior, heartbeat/watchdog,
   fence all transition effects and shield cancellation cleanup. Qualify real
   Temporal dispatch duplication, worker interruption and recovery with owned
   services; no user stack/volumes or paid providers.
5. Add the studio Releases panel and server-backed reload/cancel/retry/download UI.
   Real browser author -> saved revision -> release -> download -> actual engine
   import/browser play, equivalent gated routes, workspace/revocation boundary and
   interruption evidence. Complete runbooks/report/review, required gates and green
   CI before closing #124/M31. Continue #125 only after the appropriate dependencies.

Each implementation commit records the slice actually delivered. Never mark the
whole issue complete from ledger tests, mocks, planning or a source-only ZIP.
Preserve unrelated #109 WIP and keep the existing frontend available for testing.

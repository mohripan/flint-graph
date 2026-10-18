# Per-process-preserving local telemetry switch — 2026-10-18

Issue #108, milestone 24 / DX track 26. ADR 0033. This is the safe-switch
prerequisite to #107, not real cross-service correlation (#109), parent #72
completion or production hardening (#43).

## Delivered behavior

`flint-graph-telemetry` previews by default, supports four fixed modes, and
requires `--apply` for sequential app-only recreation. It preserves each
process's immutable image, full environment, command/entrypoint, working
directory and user; only the OTLP endpoint changes. Images are neither built
nor pulled. The selected telemetry backend must already be running/configured.
Whole-stack Compose default/provider resets and data-service recreation are not
used. Inspection, rendered environment and Docker error output stay in memory.

Preflight checks local Docker transport, explicit local app environment,
project/root ownership, singleton running processes, tracing already enabled,
unsupported custom mounts/host/network/security/resource/restart settings,
selected backend health and actual gateway mode. It renders all proposed app
environments/process settings before any change, checks for concurrent container
replacement, and compares postconditions. A partial failure returns nonzero,
safe phase/completed-service metadata and explicit non-atomic recovery guidance.
It never claims to automatically restore a lost earlier secret/config snapshot.

## Red/green and native findings

- Public CLI seam tests failed before implementation. Follow-up failing tests
  exposed missing optional-overlay discovery, ambient environment drift,
  unsupported host settings/secondary networks, concurrent app replacement,
  missing partial-failure phase and remote Docker-context acceptance. Guards
  passed their narrow tests after implementation.
- The first real combined preview found that base-only Compose could not
  discover optional services; this was fixed before any app mutation.
- A read-only native Compose probe found canonical JSON re-escapes dollar signs.
  The simplified mock initially omitted that behavior. Previously the helper
  would fail closed on dollar-containing values, not silently replace them.
  The corrected mock reproduced the failure, then the comparison decoded exactly
  the canonical renderer's escaping layer. The apply input still escapes dollars
  once in all environment/command strings. Local Compose is **5.3.1**.
- A separate disposable native Compose probe validated both serialized config
  and actual environment/command values containing `$`, `$$`, `${...}` and `=`.
  Its runtime oracle is base64-encoded independently, so matching corruption of
  expected/input strings cannot falsely pass. **1 passed in 0.61 s**. The known
  local API image ran only this Python assertion, with network disabled,
  128 MiB/0.25 CPU/64 PID limits and no volumes. `--rm` removed the owned probe.
  This real test is now in observability CI after its known sender image build.

## Live application rehearsal

The explicitly enabled rehearsal began with all four apps in base mode and
the already-qualified combined gateway running. It switched worker, relay,
cleanup and API individually to the gateway, checked **every environment value**
and immutable image against its own original snapshot, restarted the exact
owned application containers, waited for API liveness/readiness, then explicitly
returned all four to base. No environment values were printed in failure output.
The same images remained selected even though each process initially used a
different image snapshot. This preserved the existing Gemma answer/support
configuration and deterministic-test 384-dimensional embeddings.

The first rehearsal passed in **109.08 s**; a guard-hardened rerun passed in
**108.77 s**. The final post-canonical-render-fix rehearsal passed in
**110.28 s**, including all preservation/restart/base rollback assertions.

The public verification workspace's embedding/query/search-readiness metadata,
including active index and coverage, matched before/after. PostgreSQL, MinIO,
Neo4j, OpenSearch and Temporal container identities were unchanged. Public
corpus counts remained **100 documents / 100 jobs**. No upload, inference,
private document read, provider/model download, schema/index switch, volume
deletion, SMTP or remote deployment was performed. This was a quiet local
restart/recovery rehearsal, not an in-flight job drain or zero-downtime proof.

Read-only saved conversation reopening also passed at **1280** and **390** px:
the existing public two-turn answer/thread remained visible, composer stayed
reachable and no horizontal overflow appeared. The owned browser helper counted
zero mutation requests and zero SSE execution requests; no new model call or
conversation was created. Screenshots were inspected under ignored
`notes/conversation-thread-ui-reopen-{1280,390}-2026-10-18.png`; own session closed.
Frontend <http://localhost:5173> and API health endpoints returned 200.

## Verification and boundaries

Passed locally: **16** focused CLI tests; separate native string probe above;
Ruff; mypy (**162 source files**); lock consistency; deterministic Acme evaluation;
offline migration SQL (**1,061 lines**); base Compose validation; whitespace check.
Frontend tests/typecheck/build passed earlier the same session under #106;
no frontend source changed for #108. Final frozen `uv run pytest -q --tb=short`:
**1,052 passed, 22 skipped in 146.02 s**. Live/backing-service opt-ins are skipped
in that ordinary run, not counted as offline successes. CI result is recorded
in GitHub before issue closure.

An intermediate whole-suite run overlapped active helper/test editing and mixed
an already collected old Docker fixture with a subsequently imported new helper;
it produced 14 fixture-boundary failures. It was not accepted. A fresh frozen
run before the last native serialization correction passed 1,052 / 21 skipped;
the final rerun includes the new explicitly opt-in native test as well.

Not claimed/run here: live Phoenix-only/Jaeger-only application transitions,
real Temporal ingestion/query correlation, a fresh model-quality capture,
PostgreSQL-only conversation suite, production/custom Linux profile support,
remote Docker, in-flight graceful draining, atomic deployment/rollback, queue
saturation/restore, or production privacy/auth/TLS. Fixed modes have CLI tests;
their complete live application correlation matrix remains #107/#109. The helper
supports the standard local configuration and deliberately refuses guarded
customizations rather than silently dropping them.

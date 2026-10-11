# Jaeger local backend verification

Scope #105 under #72, Milestone 24. Backend-only overlay; no application export
endpoint, provider, index, database, corpus or existing service was reconfigured.
Parent #72 and #106/#107 remain open. No three-way privacy/fan-out/outage,
cross-service continuity, Grafana provisioning or production-readiness claim.

## Delivered boundary

Official Jaeger 2.22.0 pinned multiarch digest
`sha256:836b967b5abcf1f7758066aa6b348619267a2f1459f72d472840570f9bd88a17`;
native binary version/git/build checked. Custom config disables bundled AI/MCP,
UI OTLP proxy, legacy receivers, sampling/debug surfaces. Loopback UI 16686,
internal-only OTLP/gRPC; bounded memory/CPU/PIDs, capabilities dropped and
no-new-privileges. Explicit RAM trace count/batch/queue/message limits; no storage
retries or trace-data volume. See ADR 0031/runbook for precise budgets and limits.

## Passed verification

- Asset test was red before the overlay/config existed, then passed. Additional
  CPU/PID/capability contract was red before limits were added. Focused Jaeger,
  existing AI and operations asset tests: 11 passed.
- Base Compose, Jaeger profile and Jaeger+Phoenix overlay/profile composition
  validate. Composition success is not three-way runtime fan-out acceptance.
- Pinned native Jaeger validation accepted our final config and rejected the
  syntactically valid unknown-processor fixture. Native CLI/image provides wget;
  no nonexistent health utility is presumed.
- Initial health check used the wrong default path and got 404. Corrected via
  explicit v2 status-path config, revalidated and restarted Jaeger only; final
  healthy status and process budget verified. Native validation/startup alone
  would not have caught this. Experimental upstream health/exporter component
  stability and readiness-versus-delivery limits remain explicit.
- Final native SDK/OTLP/v3/surface/restart tests: two passed in 18.68s. Sender
  image was the known local application image
  `sha256:7f0ec4fa66c7772498cd46657f40159594251d560105dba636d89ecad6a59dc7`,
  invoked as an owned `--rm` container in the Jaeger network. It emitted two
  synthetic spans, read no app settings/documents and made no model/API calls.
- v3 trace `00ba09bfdf4a695810d4fdfb9654b882` had exact expected parent/child
  span IDs and shared trace ID. MCP initialize route and UI OTLP-proxy route
  both returned 404; no MCP tool was executed.
- Owned restart: trace `42afdbdc26ebd1e7931ef1d63103d89e` was retrievable before
  restart and 404 afterward. Fresh trace `57a20c578ffc46fb609a977fdfa5054a`
  was received with two correct related spans afterward. Restart discarded
  only this rehearsal's ephemeral trace history; it cannot be recovered.
  No application or data volume was stopped/deleted. Future restart tests need
  an explicit separate opt-in because they clear ALL traces in that backend.
- Own browser opened the fresh trace UI, observed both related spans, captured
  and inspected `notes/jaeger-backend-live-2026-10-11.png`, then closed its own
  session. No third-party target, user browser or private content was involved.
- Full ordinary backend regression: 1034 passed / 17 skipped in 140.81s. The
  two new live tests skip without explicit opt-in; they were run separately
  above, not counted as offline passes.
- `uv run ruff check .`, `uv run mypy` (161 source files), `uv lock --check`,
  deterministic Acme quality gate, offline migration SQL (1061 lines) and
  `git diff --check` passed. Two initial embedded-sender string lint line-length
  errors were corrected before passing lint.
- API health and frontend localhost:5173 returned 200; Jaeger stayed healthy
  with 536870912-byte memory, one CPU and 128 PID limits. Existing optional
  Phoenix/gateway containers were not removed or silently restarted.

CI now includes native Jaeger positive/negative validation, composition checks
and real delivery/restart/surface checks using an isolated locally built sender
image. CI result is recorded in the issue after push, not presumed here.

Not rerun: frontend unit/build/full chat browser suite, fresh model-quality
capture, PostgreSQL-specific tests or another Phoenix/Tempo live smoke locally.
No application Python/auth/schema/UI behavior changed. Existing CI retains its
Phoenix/Tempo checks. Not qualified: max-trace saturation/eviction ordering,
long-running capacity, arbitrary payload defense at the raw Jaeger receiver,
cross-destination privacy/slow-sink isolation, cross-service profile rollout,
production auth/TLS/sampling/access/retention/erasure/restore. These remain
#106/#107/#43; trace count/config limits are not a proven production byte quota.

The local backend remains available at http://127.0.0.1:16686. It does not yet
receive application traces; only synthetic rehearsal traces were emitted.

# ADR 0032: Shared-privacy Jaeger fan-out with bounded destination failure

Date: 2026-10-18. Status: accepted for local qualification. Milestone 24, #106
under #72. Extends ADR 0031; application rollout is #107, production is #43.

## Decision

Add an explicit third Compose file, `compose.jaeger-gateway.yaml`, after the
backend overlay. It selects the existing Collector 0.162.0 and shared
`otel-gateway.yml` privacy processors, then merges one Jaeger exporter and a tiny
destination-list file. Native multi-config merging preserves maps and replaces
the trace exporter list. No experimental list-append flag, copied privacy
policy, second application SDK, or additional application exporter is used.

The default `jaeger-only` mode sends traces to LGTM and Jaeger. Explicit
`FLINT_GRAPH_JAEGER_GATEWAY_MODE=jaeger-phoenix`, with the AI overlay/profile,
sends to all three. Unknown mode filenames fail native validation/startup.
Metrics and logs still go only to LGTM. Base and existing Phoenix configurations
are unchanged. Including the overlay declares application endpoint overrides,
but gateway qualification starts only named telemetry services; it must not
silently recreate application containers or change their model configuration.

Every selected trace destination receives the same post-processor data:
resource/span attribute allowlists, all events dropped, status descriptions
cleared, and transformation/filter errors propagated rather than ignored.
This is not arbitrary secret detection: span names, allowed metadata values,
span links, metrics/log bodies and third-party instrumentation require separate
production review. Do not put customer content in those fields. Local raw
OTLP listeners and UIs are not tenant-authorized production interfaces.

The Jaeger exporter has a two-second per-attempt timeout, two consumers and a
64-request in-memory queue. Queue size is requests, not bytes. Overflow rejects
without blocking and callers do not wait for destination completion. Retry
backoff starts at one second, is bounded by two seconds, and stops after the
ten-second retry budget. This is not a ten-second enqueue-to-delivery SLA:
queue wait and attempt completion matter. Expired/overflowed Jaeger data can be
lost while the other destinations continue. Restart also loses buffered data.
The gateway retains its 768 MiB container and 512 MiB processor memory limits.
No saturation throughput/capacity or lossless delivery claim follows.

Expose native Collector metrics only on host loopback port 18888 for queue
capacity/occupancy, in-flight work and failed exports. Operational alert routing
and production collection remain #43; a configured metric is not an alert.

Provision fixed Grafana datasource UID `flint-graph-jaeger` pointing only at
`http://jaeger:16686`, non-default and non-editable. `prune: true` removes that
owned datasource when the optional file is absent on base-only recreation.
Tempo, the operations datasource/dashboard and the LGTM volume remain intact.
Recreating LGTM briefly interrupts its local endpoints; do not run `down -v`
or remove orphans to roll back an optional trace destination.

## Alternatives and gates

Copying full gateway configurations would make privacy policies drift. Sending
directly from each SDK to multiple backends multiplies queues and bypass paths.
Keeping only Tempo is cheaper, but omits the requested optional Jaeger workflow.
The shared, explicitly selected pipeline is a bounded incremental change.

Native positive/negative validation, real OTLP IDs/structure/privacy in selected
backends, fixed Grafana proxy lookup, actual paused-socket expiry/recovery,
Jaeger-only delivery with Phoenix stopped, and datasource prune rollback are
qualified separately from asset shape tests. See the
[delivery report](../reports/2026-10-18-jaeger-gateway.md) and
[runbook](../runbooks/jaeger-gateway.md). No model request is required. #72 stays
open until #107 cross-service propagation and application switch/rollback are
qualified. Production authentication, TLS, retention, sampling and comprehensive
privacy controls are not delivered by this local overlay.

## Primary references

Reviewed 2026-10-18:
[pinned Collector exporter helper](https://github.com/open-telemetry/opentelemetry-collector/blob/v0.162.0/exporter/exporterhelper/README.md),
[Grafana Jaeger provisioning](https://grafana.com/docs/grafana/latest/datasources/jaeger/configure/),
and [Grafana datasource pruning](https://grafana.com/docs/grafana/latest/administration/provisioning/).
Native runtime tests, rather than assumptions about queue/config defaults,
qualify this release's selected behavior.

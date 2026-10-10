# Local Phoenix and trace fan-out

This opt-in profile is a developer rehearsal, not a production deployment.
Phoenix and the gateway bind loopback. Phoenix uses its own retained SQLite data
volume; no application PostgreSQL schema is changed. Do not expose these
unauthenticated endpoints through a public reverse proxy.

## Start safely

Validate and start just the telemetry tools without recreating existing API or
worker containers:

```powershell
docker compose -f compose.yaml -f compose.ai-observability.yaml --profile ai-observability config --quiet
docker compose -f compose.yaml -f compose.ai-observability.yaml --profile ai-observability run --rm --no-deps otel-gateway validate --config=/etc/otelcol/config.yml
docker compose -f compose.yaml -f compose.ai-observability.yaml --profile ai-observability up -d observability phoenix otel-gateway
```

Phoenix UI: <http://127.0.0.1:6006>. Grafana:
<http://localhost:3000/d/flint-graph-operations>. Host OTLP gRPC ingress:
`http://127.0.0.1:14317`; application containers use `http://otel-gateway:4317`.
The overlay selects that endpoint for API, worker, relay and cleanup. To switch
running application processes, use the same two Compose files and profile when
recreating those services, **preserving their current provider/model environment
variables**. A bare Compose restart does not change container configuration;
a fresh up with missing provider variables can reset local models to defaults.

Do not use the overlay without `--profile ai-observability`: it would point the
application at a gateway that was not selected. Revert to base `compose.yaml`
and recreate the affected application containers to return to direct LGTM OTLP.
Never delete data volumes to switch profiles.

## Trace contract and budgets

One shared provider-call span carries OpenInference kind/model/provider metadata.
The gateway fans traces to Phoenix and LGTM, metrics/logs only to LGTM. It
allowlists resource/span attribute keys, clears status messages, and drops all
span events so framework exceptions cannot export raw message/stack payloads.
Transformation/filter errors propagate and reject that batch rather than export
the original. Span names and values of approved keys must still be safe; this is
not a general arbitrary-text/PII detector. Production hardening is M24 #43.

The gateway has a 768 MiB container limit, a 512 MiB memory limiter with 128 MiB
spike allowance, batches capped at 512 spans/items, 256-request queues and 60 s
maximum retry windows. These bound local resources, not durable delivery. Queues
are in memory, and exhausted retries/full queues may drop telemetry. Monitor
export failures and size retention before production. Phoenix's local 1 GiB
limit and persistent SQLite volume are not a tested production capacity target.

No automatic OpenLLMetry SDK is installed and no model content is exported.
Custom provider spans already own timing and classification. Optional future
instrumentation must disable content capture and avoid duplicate span ownership.
No stdout log shipper is added here; a logs pipeline only handles already-OTLP
logs. Structured log collection and ELK selection remain #42.

## Real fan-out/privacy smoke, without inference

```powershell
$env:FLINT_GRAPH_AI_OBSERVABILITY_INTEGRATION = "1"
uv run pytest tests/integration/test_ai_observability_live.py -q
Remove-Item Env:FLINT_GRAPH_AI_OBSERVABILITY_INTEGRATION
```

The test emits a real provider error span and a parent with deliberately private
sentinel attributes/events. It checks the same trace in Phoenix's public REST API
and Tempo through Grafana, verifies AI classification, and verifies that the
sentinel was removed. It makes no model calls or corpus mutations. Two sanitized
smoke spans remain in the local `flint-graph` Phoenix project for inspection.
Ordinary pytest skips this test unless explicitly enabled.

During development, native Collector validation accepted an event-clearing
expression that failed at runtime. The live smoke caught it; the final config
uses the supported span-event filter and passed. Syntax checks alone are not
enough for privacy acceptance.

## Production follow-ups

Require authenticated/TLS OTLP, protected operator UIs, retention/erasure,
sampling/capacity/delivery monitoring and restore drills before production.
Phoenix traces do not replace PostgreSQL query provenance, audit or usage.
Email/webhook delivery remains separately configured through Alertmanager #41;
no message is sent by starting this profile.

# Opt-in local Jaeger backend

#105 is the backend-only slice of #72. Gateway fan-out/Grafana lookup (#106),
cross-service propagation/application switching (#107) and production (#43) are
not delivered by starting it. See [ADR 0031](../adr/0031-opt-in-bounded-jaeger-local-backend.md).

## Validate and start only the backend

```powershell
docker compose -f compose.yaml -f compose.jaeger.yaml --profile jaeger config --quiet
docker compose -f compose.yaml -f compose.ai-observability.yaml -f compose.jaeger.yaml --profile ai-observability --profile jaeger config --quiet
docker compose -f compose.yaml -f compose.jaeger.yaml --profile jaeger run --rm --no-deps jaeger validate --config=/etc/jaeger/config.yml
docker compose -f compose.yaml -f compose.jaeger.yaml --profile jaeger up -d --no-deps --wait --wait-timeout 60 jaeger
```

UI: <http://127.0.0.1:16686>. Default application services and model/index
settings are untouched. OTLP/gRPC is `jaeger:4317` inside the Compose network,
not a host port. Only sanitized gateway traffic should be connected after #106;
do not redirect application exporters directly to this raw backend. No automatic
content-capturing SDK or legacy Jaeger client is installed.

Readiness: `docker exec flint-graph-jaeger-1 wget -q -O - http://127.0.0.1:13133/health/status`.
Self-metrics are container-local on port 8888. Readiness is not a delivery receipt.
The custom config disables MCP/AI, UI ingestion proxy, legacy/sampling/debug
surfaces. Unauthenticated UI access is local operator access, not tenant auth.

## Real no-inference delivery test

Build or select a known local app image for a disposable SDK sender. This does
not start application services or read their settings/secrets:

```powershell
$env:FLINT_GRAPH_JAEGER_INTEGRATION = '1'
$env:FLINT_GRAPH_JAEGER_SENDER_IMAGE = docker inspect flint-graph-api-1 --format '{{.Image}}'
uv run pytest -q -s tests/integration/test_jaeger_backend_live.py --tb=short
Remove-Item Env:FLINT_GRAPH_JAEGER_INTEGRATION
Remove-Item Env:FLINT_GRAPH_JAEGER_SENDER_IMAGE
```

Without an existing API image, `docker compose build api` builds the sender
image without starting API/worker/database/model services; explicitly select
its local tag. The test launches an owned `--rm` sender in the backend's network,
emits two synthetic spans, retrieves their exact IDs/parent structure through
`/api/v3/traces/{trace_id}`, and probes disabled MCP and UI OTLP proxy routes.
It does not read customer documents, call a model, execute MCP tools or send
external notifications. Normal pytest skips this opt-in test.

## Restart and rollback

Memory storage caps retained trace count at 10,000, not bytes or retention time.
Older traces may be evicted at capacity; all RAM traces disappear on process
exit. Bounded queue/batch/container resources can still drop traces or cause
restart under overload. This is not a durable audit/provenance store. The image
declares a temporary `/tmp` volume; this is not trace persistence, and we do not
delete volumes during verification.

Only on an owned disposable backend with no valuable history, additionally set
`FLINT_GRAPH_JAEGER_RESTART_REHEARSAL=1` before the test. This restarts **Jaeger
only and clears ALL its ephemeral traces**, verifies old trace 404, then verifies
fresh delivery. Remove that variable afterward. Never enable this rehearsal
against a shared backend merely to run the normal delivery test.

To stop the locally added backend without touching existing services/volumes:

```powershell
docker compose -f compose.yaml -f compose.jaeger.yaml --profile jaeger stop jaeger
```

This stops RAM retention; traces cannot be recovered. Do not use `down -v` or
`--remove-orphans`. Base and Phoenix overlays are unchanged, so backend-only
rollback needs no application/provider reconfiguration. End-to-end rollout,
destination-outage isolation, privacy and Grafana datasource remain #106/#107.

The CI observability job validates native positive/negative configs, builds a
known sender image and runs delivery/restart against its own isolated local
stack. It makes no inference/SMTP calls. Registry/dependency downloads are not
an air-gapped workflow. Production operator access, TLS, sampling, capacity,
retention/erasure and restore remain separately gated by #43.

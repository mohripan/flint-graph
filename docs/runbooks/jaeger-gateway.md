# Local Jaeger gateway qualification

Scope: #106 / ADR 0032. Local unauthenticated tools only. The backend must first
pass the [Jaeger runbook](jaeger-local-backend.md). Do not use these commands to
roll out production or silently change running application exporters/models.

## Select and validate

From the repository root, choose one mode. Jaeger-only needs no Phoenix:

```powershell
$taskCompose = @('-f','compose.yaml','-f','compose.jaeger.yaml','-f','compose.jaeger-gateway.yaml','--profile','jaeger')
$env:FLINT_GRAPH_JAEGER_GATEWAY_MODE='jaeger-only'
docker compose @taskCompose config --quiet
docker compose @taskCompose run --rm --no-deps otel-gateway validate --config=/etc/otelcol/config.yml --config=/etc/otelcol/jaeger-exporter.yml --config=/etc/otelcol/jaeger-only.yml
```

For LGTM + Phoenix + Jaeger, use the AI overlay before the Jaeger overlays and
explicitly select the three-destination file:

```powershell
$taskCompose = @('-f','compose.yaml','-f','compose.ai-observability.yaml','-f','compose.jaeger.yaml','-f','compose.jaeger-gateway.yaml','--profile','ai-observability','--profile','jaeger')
$env:FLINT_GRAPH_JAEGER_GATEWAY_MODE='jaeger-phoenix'
docker compose @taskCompose config --quiet
docker compose @taskCompose run --rm --no-deps otel-gateway validate --config=/etc/otelcol/config.yml --config=/etc/otelcol/jaeger-exporter.yml --config=/etc/otelcol/jaeger-phoenix.yml
```

Native validation must reject a nonexistent destination file, and the existing
invalid Collector fixture must reject its unknown component. YAML parsing alone
is insufficient. The shared file supplies every privacy processor; the small
mode files replace only the trace exporter list. Modes do not auto-detect a
running Phoenix. Do not select `jaeger-phoenix` without starting Phoenix.

## Start only telemetry and verify

Check port availability first. Host ingress: gateway 127.0.0.1:14317, gateway
self-metrics 127.0.0.1:18888, Jaeger UI 127.0.0.1:16686, optional Phoenix
127.0.0.1:6006. The existing base LGTM host bindings are unchanged; these files
do not turn that base stack into a protected production boundary.

```powershell
# Recreates only named telemetry services; LGTM endpoints briefly restart.
$taskServices = @('observability','jaeger','otel-gateway')
if ($env:FLINT_GRAPH_JAEGER_GATEWAY_MODE -eq 'jaeger-phoenix') { $taskServices += 'phoenix' }
docker compose @taskCompose up -d --no-deps --wait --wait-timeout 120 @taskServices
$env:FLINT_GRAPH_JAEGER_GATEWAY_INTEGRATION='1'
uv run pytest tests/integration/test_jaeger_gateway_live.py -q -s -k 'not rollback'
```

The test sends synthetic parent/child spans, runs the actual provider telemetry
wrapper without a provider request, and retrieves exact IDs from native Jaeger
v3, Tempo through Grafana, and (if selected) Phoenix. Sentinel prompt, answer,
evidence, vector, credential, exception, event and resource payloads must be
absent. All returned events/status descriptions must be empty. This does not
test arbitrary secrets inside allowed metadata, names, links or log bodies.
Grafana datasource UID is `flint-graph-jaeger`; Tempo stays `tempo`.

On an **owned local backend**, optionally enable the brief paused-socket drill:

```powershell
$env:FLINT_GRAPH_JAEGER_PAUSE_REHEARSAL='1'
uv run pytest tests/integration/test_jaeger_gateway_live.py -q -s -k stalled
Remove-Item Env:FLINT_GRAPH_JAEGER_PAUSE_REHEARSAL
```

It resolves the exact Compose Jaeger container, checks ownership/running state,
pauses it, and always attempts unpause in `finally`. Selected other backends
must receive the trace before the retry budget expires. Native
`otelcol_exporter_queue_capacity{exporter="otlp/jaeger"}` is 64, queue occupancy
stays bounded, in-flight work drains, failed-span count increases, the expired
trace is absent at Jaeger after unpause, and a fresh trace reaches all selected
destinations. Dropped data is not recovered or replayed. A failed/interrupted
drill may need `docker unpause <exact-owned-container-id>` after inspecting its
state. This is low-volume fault qualification, not saturation benchmarking.

## Rehearse removal without losing stored data

For Jaeger-only qualification, stop only Phoenix and recreate only the gateway
with the Jaeger-only selection above. Run the destination test again: unused
Phoenix exporter configuration must not require a live Phoenix.

To remove the optional Grafana datasource, recreate only LGTM with base config:

```powershell
docker compose up -d --no-deps --wait --wait-timeout 120 observability
$env:FLINT_GRAPH_JAEGER_DATASOURCE_ROLLBACK='1'
uv run pytest tests/integration/test_jaeger_gateway_live.py -q -k optional_datasource_rollback
Remove-Item Env:FLINT_GRAPH_JAEGER_DATASOURCE_ROLLBACK
```

Jaeger datasource must return 404, while Tempo and operations datasource remain
200. This deletes only the optional datasource configuration, not trace data;
re-enabling the overlay reprovisions it. Existing Phoenix-only gateway can be
restored with its two-file overlay and named telemetry services. Do not stop a
gateway still used by applications before restoring their previous endpoint.
Application profile/model preservation and switching is #107, not this drill.
Never use `down -v`, prune Docker volumes or remove orphan containers here.

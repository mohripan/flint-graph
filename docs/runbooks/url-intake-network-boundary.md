# URL intake network boundary

See [ADR 0030](../adr/0030-connection-bound-document-url-intake.md).

Production/staging: keep `FLINT_GRAPH_ALLOW_PRIVATE_URL_INTAKE=false`, use a
finite positive `FLINT_GRAPH_INTAKE_URL_TIMEOUT_SECONDS` (default 10), choose an
intentional `FLINT_GRAPH_MAX_URL_INTAKE_BYTES`, and restrict application egress
at the deployment network. URL user information is always rejected. HTTP proxy
environment variables and environment trust-root overrides are not used by
intake. Do not route intake through an unqualified custom injected HTTP client.
Other model/object-store HTTP adapters are outside this boundary.

DNS resolves asynchronously; all returned addresses must be permitted before
the first is selected. DNS errors/timeouts, mixed or nonpublic results, HTTP
errors, TLS mismatch and excessive redirects/content return safe 400 errors
before document intake persistence. A permitted destination with an unreachable
first IP fails without trying another IP or automatically retrying. If a large
report exceeds the whole-fetch budget, an operator may deliberately increase
the finite timeout or use an authorized upload; do not disable the boundary.

Local private-network opt-in remains available for owned development servers.
It intentionally permits local network access and is not production protection.
No customer document is needed to qualify this boundary:

```powershell
uv run pytest -q tests/unit/test_url_fetcher_security.py tests/integration/test_url_fetcher_transport.py tests/integration/test_intake.py tests/unit/test_config.py --tb=short
```

The HTTPS fixtures use ephemeral keys and a disposable trust root, never
`verify=False`. Positive, hostname-mismatch and cross-host redirect cases check
real TLS and HTTP. Production certificates/credentials are not used.

## Isolated real-socket rebinding rehearsal

`ops/security/verify_url_dns_network.py` is Linux-only verification tooling,
not a service/startup script. Never run it in a host namespace or with
`--network host`. It refuses non-Docker or non-loopback-only environments and
requires `--isolated-network`. Use a known locally built application image:

```powershell
$taskApiImage = docker inspect flint-graph-api-1 --format '{{.Image}}'
docker run --rm --network none --user 0 --cap-add NET_ADMIN --sysctl net.ipv6.conf.all.disable_ipv6=0 --entrypoint /app/.venv/bin/python --mount type=bind,source=C:/Projects/flint-graph/ops/security/verify_url_dns_network.py,target=/tmp/verify.py,readonly $taskApiImage /tmp/verify.py --isolated-network
```

Adapt only the explicit workspace path if needed. Root/NET_ADMIN applies solely
to the disposable network namespace so it can assign synthetic public addresses
to loopback. The production API stays non-root and gains no capability. No
volumes, database, corpus, credentials or existing service configuration is
mounted or mutated. `--rm` removes this owned disposable container after exit.

Success requires IPv4 and IPv6 public-report requests through the native HTTP
stack, preserved Host, ignored ambient proxy, fresh-request and redirect DNS
denial, and zero sentinel TCP contacts. Synthetic changing DNS answers are
injected at the OS resolver seam; numeric socket destinations are not remapped.
Both addresses are local only inside this network-isolated namespace. Preserve
the exact output and image in the issue report. A DNS-preflight/string-filter
test or container startup alone is not a pass.

Still required independently: restricted production routing/egress, appropriate
resolver and proxy posture, request/rate limits, parser resource isolation and
the broader agent threat-model runtime controls (#81).

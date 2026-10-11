# ADR 0030: Connection-bound document URL intake

Date: 2026-10-11. Status: accepted for the existing HTTPURLFetcher path.
Scope: #104, FG-05, Milestone 29; complements ADR 0029 and #103.

## Decision

Use a small HTTPX async transport wrapper to resolve each original/redirect
destination once and pass a validated numeric IP to the native transport.
Validate the entire answer set before selecting its first address. Outside the
explicit private-network opt-in, require global unicast addresses, excluding
scoped IPv6, 6to4, Teredo and the well-known NAT64 prefix. IPv4-mapped local
targets, shared carrier-grade NAT, documentation and unspecified ranges are
not public destinations. Native public IPv4 and IPv6 remain supported.

Preserve the original Host header and use HTTPcore's documented `sni_hostname`
extension for TLS hostname/certificate validation. Return the original URL for
relative redirect resolution and provenance, not the dialed IP. Disable proxy
environment variables at both client and native transport, native connection
retries, HTTP/2 and keepalive pooling. IP-based pooling must not reuse a
connection authenticated for a different hostname. Every redirect is a fresh
policy check and connection. The existing limit is six HTTP requests total.

The configured finite positive intake timeout is now one whole-fetch budget
covering DNS waits, all redirects and body reads, as well as per-operation HTTP
timeouts. Existing byte limits apply to declared length and streamed decoded
content. Safe errors never expose resolver/driver diagnostics or credentials.
The #103 user-information guard still precedes original/redirect dispatch even
in local private-network mode. Nonfinite timeout settings are rejected.

## Alternatives and trade-offs

- A DNS preflight alone leaves a second-resolution TOCTOU gap and is rejected.
- A custom HTTPcore network backend could preserve pooling, but would add
  lower-level stream/exception adaptation and a direct dependency. The public
  HTTPX transport wrapper and documented SNI extension are smaller here.
- A restricted egress proxy/network policy is appropriate defense in depth for
  deployment, but cannot be inferred from a developer Compose environment.

The selected first IP may be unavailable even when another public answer works.
There is deliberately no automatic fallback/retry; the caller receives a safe
failure. Fresh per-request DNS and TLS increase latency, which is acceptable for
document intake rather than a high-volume crawler. No other HTTP adapter,
provider, graph, query or workspace policy changes. Asyncio is the API runtime.

## Boundary and residual limits

This controls application destination selection, not the host's routing, NAT,
DNS integrity, transparent network intermediaries or a compromised operator.
Custom DNS64/NAT64 translators need explicit restricted egress, not an exception
silently added to the public classifier. Caller-supplied `http_client` remains a
trusted application/test seam; it is not exposed through API parameters. The
production dependency constructs the default pinned transport. Local private
opt-in intentionally permits local destinations and is not production SSRF
protection. Deployment owners must keep it disabled and restrict egress.

Timeout cancellation bounds the awaiting request, not forcible termination of
an OS resolver thread. It is not a CPU/memory quota for parsers or decompression;
those boundaries and process isolation remain separate work. No source
truthfulness, agent/tool egress policy, sandbox or production certification is
implied.

## Verification

Red-first fetcher/TCP tests, API denial-before-persistence, real owned HTTPS
Host/SNI/mismatch/redirect isolation, and IPv4/IPv6 real-socket DNS rebinding in
a disposable `--network none` container are recorded in the
[verification report](../reports/2026-10-11-url-intake-dns.md). The rehearsal's
public numeric addresses exist only on its isolated loopback interface; there
is no external route or third-party HTTP target.

Primary API references checked on 2026-10-11:
[HTTPX transport wrappers](https://www.python-httpx.org/advanced/transports/),
[HTTPcore SNI extension](https://www.encode.io/httpcore/extensions/), and
[HTTPX environment controls](https://www.python-httpx.org/environment_variables/).
Verified with locked HTTPX 0.28.1 / HTTPcore 1.0.9; repeat native TLS/network
qualification when these dependencies change.

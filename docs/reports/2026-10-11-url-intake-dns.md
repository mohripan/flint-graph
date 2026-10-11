# Connection-bound URL intake verification

Scope #104, FG-05, Milestone 29. See
[ADR 0030](../adr/0030-connection-bound-document-url-intake.md) for the decision,
availability/latency trade-offs and residual boundaries. Default intake now
validates all resolved addresses and dispatches a numeric destination with
original Host/TLS hostname. No ambient proxies, retries or pooled connection
reuse; DNS, redirects and body share a finite positive deadline. No new model,
dependency, schema, source document or production network policy.

## Tests and checks

- The initial tracer test's resolver binding was corrected after a DNS error;
  then it reproduced the old double-resolution behavior: a synthetic public
  precheck led to the local sentinel body at the mocked TCP boundary. The new
  transport returned only the public report and dialed the validated address.
- Red-first DNS whole-deadline, finite timeout/body-limit and transition-address
  tests failed before their controls. The initial NAT64 check returned a safe
  connection failure, not a policy denial; the test was tightened to prohibit
  TCP entirely, then passed with the shared address policy. No successful
  third-party connection or production exploit is claimed.
- Focused fetcher/native TLS/intake/config command from the runbook: 93 passed.
  Includes mixed IPv4/IPv6 answers, mapped/local/shared/transition addresses,
  redirect rebinding, proxy/retry denial, safe DNS errors, trickling body, six
  request limit, content limit and API denial before document/object persistence.
- Native owned TLS fixtures passed: allowed Host/SNI and final URL, certificate
  hostname mismatch without HTTP, and redirect to another hostname at the same
  IP/port requiring fresh certificate verification rather than TLS reuse.
  Ephemeral trust root/keys only; verification was never disabled.
- Full backend regression was rerun after the final configuration test was added:
  1033 passed / 15 skipped in 141.05s. An earlier run
  collected before that addition had 1029 passes / 15 skips in 141.29s.
- Ruff, mypy (161 source files), lock, Compose, deterministic Acme quality gate,
  offline migration SQL (1061 lines) and diff checks passed. A rehearsal-tool
  blocking-path lint error was corrected before the passing lint check.

## Isolated actual network rehearsal

`ops/security/verify_url_dns_network.py` ran through the native HTTP stack in
an owned disposable Docker `--network none` namespace. Synthetic public IPv4
`8.8.8.8` and IPv6 `2606:4700:4700::1111` existed only on this namespace's
loopback interface; both real sentinel sockets were loopback-only in it. No
database/volumes/corpus/secrets were mounted, and there was no external route.
The OS DNS seam supplied changing answers; numeric TCP destinations were not
remapped to substitute sockets. Production API capabilities stayed unchanged.

For each family: public report request succeeded with original Host; a fresh
request with a local answer was denied; an allowed redirect source followed by
a local answer was denied; two report HTTP requests and zero sentinel TCP
contacts. Ambient proxy pointed at the trap and was ignored. DNS sequences:

- IPv4: public, 127.0.0.1, public, 127.0.0.1.
- IPv6: public, ::1, public, ::1.

The first setup failed as the image's non-root user could not assign test
addresses. Rerun as root with NET_ADMIN inside the isolated disposable container
passed; these privileges are not granted to any production service. The final
script refuses non-Docker/non-loopback-only environments and requires the
explicit isolated-network flag. Containers were automatically removed, which
removed only their temporary synthetic network configuration.

The final rehearsal passed on the rebuilt running API image
`sha256:7f0ec4fa66c7772498cd46657f40159594251d560105dba636d89ecad6a59dc7`,
without source-code mounts. Initial pre-build qualification used image
`sha256:5b237acef1c6effb382d874e8d7ace0b922449ee520fe6345d32475775c0436c`
with the two changed transport files mounted read-only. These working-tree
images predate the final #104 commit; no later commit/image equivalence is assumed.

## Running API and frontend

API-only rebuild preserved existing provider selections; migration remained
`0016_conversation_ledger`. Orphaned optional observability containers were left
alone. No worker, corpus, data volume or broader Compose migration was changed.

On the running image: default fetcher retrieved an owned local `Public report`
with preserved Host/content type/final URL and no Authorization. Current local
private-network opt-in was explicit; this does not attest production private
denial. Public API intake of a reserved `.invalid` hostname returned safe 400;
100 public documents/jobs and readiness were unchanged. Credential original/
redirect API denials still returned 400 with zero rejected-target requests and
unchanged 400 public-prefix objects.

Two owned verification-harness errors were corrected, not product behavior:
the original credential report's exclusive output path already existed (a new
path preserved it); synchronous child execution blocked its own HTTP server
and timed out (async execution let the owned server respond). Failed attempts
are not counted as passes. Local passed reports are
`notes/url-dns-api-live-2026-10-11.json` and
`notes/url-credential-after-dns-live-2026-10-11.json`.

The browser skill reopened the existing public two-turn conversation at 1280
and 390 pixels, inspected screenshots, and checked no horizontal overflow and
a visible composer. Zero mutation/inference/SSE requests; owned browser session
closed. Frontend stays on localhost:5173 for the user.

Not rerun: frontend unit/build/full browser suite, new model-quality capture,
PostgreSQL-specific conversation suite, private corpus or production network
attacks. No OIDC/auth/conversation/schema behavior changed. Parser CPU/memory,
decompression isolation, OS resolver-thread hard cancellation, arbitrary routing/
NAT/translators, future tool/agent egress and production rollout remain separate
gates. #81 and Milestone 29 remain open. CI outcome is recorded after push.

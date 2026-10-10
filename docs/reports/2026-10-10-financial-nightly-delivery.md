# Financial nightly harness rehearsal — 2026-10-10

Issue #53 implementation: fresh public query/SSE/retrieval/provenance capture,
per-run actual token rollups, strict installed-Ollama preflight, exact prepared
public workspace, repeat fingerprint checks, three foreign-workspace 404 probes
per captured query and redacted artifacts. No provider/model downloads or paid
calls. Deterministic embeddings remain a fixture, not real semantic embedding proof.

Workspace `2eab2f78-208e-4eb9-97a2-087e40af0525`, index
`fc8aa4e9-6b7f-4283-99cf-efc850a472e1`: 100 active indexed FinQA excerpts.
Model fingerprint `669a19cae19de22a089a9c681f1e6d37a1d5412ba479ff0de316c3d988749833`.
Installed Gemma answer/support digest is recorded by the developer profile report.
Separate isolation workspace `5481d172-03e0-4fab-89cb-d01e55977172` initially empty.
Subsequent user upload/deletion there is not part of the financial corpus or gold.

The initial rehearsal completed nine cases, then cancelled the ambiguous query
because HTTP read timeout was 30 seconds despite a 90-second query budget. A
public HTTP regression now verifies the SSE timeout uses the query budget. The
initial incomplete result was not accepted as quality evidence or a baseline.

The second fresh rehearsal completed all 12 cases: 9/10 answerable cases useful,
abstention accuracy 11/12, expected-abstention recall 1/2, retrieval recall@5 0.95,
required-citation satisfaction 0.9, citation validity 1.0, supported-claim ratio
0.9286 and one unsupported claim. p95 latency 16.47 seconds. All tenant probes
passed. Observed usage: 82,177 input and 3,275 output tokens; compute cost unknown.
Multi-report synthesis and ambiguous wording failed, so the strict gate FAILED.
Neither rubrics nor thresholds/baselines were weakened. Findings became #59/#60.
This capture's usage-completeness flag incorrectly remained false on quality
failure; a regression fixes the flag independently of quality outcome.

GitHub activation is pending a reachable authorized HTTPS deployment and explicit
operator variables/secrets. Current secrets/variable listings were empty. External
human financial-rubric review and accepted performance baselines remain pending;
#53 stays open. No remote quality claims, live hosted providers, real embeddings,
large-corpus scale, deployed revision attestation or production OIDC rehearsal.

Frontend was already running at `http://127.0.0.1:5173`; left running unchanged.
HTTP page/API proxy returned 200; isolated browser selected the financial workspace
and showed `Documents (100)` and query history. Frontend tests (6), typecheck and
production build passed. No frontend source changes were needed.

# Trusted Linux Godot child qualification

Scope: #124's explicitly prepared image and trusted child protocol. This is not
the host build worker, Temporal integration, publication/download API or Releases
UI. Release creation remains disabled in the ordinary local API.

The Linux4.7.2 engine archive was downloaded from the official release and checked
against both SHA-256 and SHA-512; its extracted146,414,384-byte binary and existing
single-threaded templates match the committed platform pins. The operator tool
creates only a new build context, rechecks copied bytes against their expected
hashes and requires `--build` to construct an image. The base is pinned by digest;
resolved fontconfig packages are bound by the resulting immutable image ID.
Runtime/recipe/child hashes produce a separate toolchain identity. No application
startup or job invokes this preparation tool. The Windows source-export path
and previously qualified toolchain metadata remain unchanged.

The image checks input runtime files against its own independent hashes. An
updated input manifest cannot authorize changed scripts. Only nineteen known
source files enter scratch; unrelated input files are ignored. Closed manifest
parsing rejects duplicates, unknown fields, wrong versions/hash identities and
recursion failure. Fixed headless import/export commands produce the seven-file
web inventory. Status contains only safe codes or sizes/hashes, never raw logs.

Engine output uses nonblocking bounded reads with a small error-marker window.
Stage deadlines include pipe draining, and Linux process-group cleanup handles
descendants. Review first reproduced a7.08-second hang with a0.2-second timeout
when a descendant retained stdout; the regression now completes within its bound.
The copied-context hash race and uncontrolled nested JSON failure were also fixed.
The same reviewer independently passed all13 focused offline tests after fixes.

## Actual image proof

Qualified image:
`sha256:0e0ee5625ab13bd5a4ceade377487a88c78acc549db8261679ea36c0e7e18511`.
Toolchain:
`a5ba78d233e18bdfa2f9d56b9118134e492071d9cbf14d8bec10709628809af4`.
These identify this local qualification build; an operator needs the corresponding
available image, not a mutable tag or an implicit pull fallback.

Three actual cases passed:

1. Export the original three-ending Lantern fixture with its art references removed
   for this text-only hosted boundary. Decode its fixed child USTAR stream, compare
   every file's size/hash to child status, and produce bounded source/web proof ZIPs.
2. Change `runtime/player.gd` and its input-manifest hash. The image rejects it with
   `input_integrity` before Godot rather than trusting the supplied manifest.
3. Leave a detached child without a supervising worker or host stop. Its independent
   watchdog exits124 after182.219 observed seconds; inspection confirms no OOM kill.

Effective inspection verified UID/GID10001, network`none`, read-only root, dropped
capabilities/no-new-privileges,2 CPUs,1 GiB memory/equal swap,128 PIDs,256 MiB
tmpfs and exactly one read-only input bind. A synthetic host-environment secret
canary was absent from the child. No provider/DB/store credentials, writable host
output or Docker socket was mounted. Owned containers were removed after label
verification; no user services or volumes were altered.

[Qualification receipt](evidence/narrative-build-child-2026-10-30/qualification.json),
[watchdog receipt](evidence/narrative-build-child-2026-10-30/watchdog.json), and
[image preparation identity](evidence/narrative-build-child-2026-10-30/toolchain.json).
Local proof ZIPs remain in ignored operator output. They are not published
artifacts; the final web distribution still needs its external notices/licenses
and release manifest. No new browser-play or final-game parity claim is made here.

## Verification

Passed:

- `uv run pytest tests/unit/test_narrative_build_child.py tests/unit/test_narrative_builder_prepare.py -q --tb=short`:
  13 passed, including changed image-pinned scripts, safe diagnostics, stalled
  engines, inherited stdout, malformed/duplicate/unknown manifests and source-copy
  replacement before receipt issuance.
- `uv run pytest -q --tb=short`:1309 passed,50 skipped in179.18 seconds.
  The subsequently added opt-in watchdog file also independently skips without
  explicit activation (`1 skipped`); the full run predates that test-only addition.
- Explicit image/toolchain/evidence settings plus watchdog opt-in:
  `uv run pytest tests/integration/test_narrative_build_child_live.py tests/integration/test_narrative_build_watchdog_live.py -q --tb=short`:
  3 passed in190.53 seconds against the final image.
- `uv run ruff check .`; `uv run mypy` (183 source files); `uv lock --check`.
- The deterministic Acme evaluation command from `AGENTS.md`, unchanged gate.
- Offline Alembic SQL through0018 (1212 lines), `docker compose config --quiet`,
  and `git diff --check`.
- Explicit `tools/narrative/prepare_builder.py ... --build` against verified local
  inputs; receipt/image identity and actual child tests above match that context.

Native PostgreSQL and frontend/browser flows were not repeated for this child-only
slice; their behavior did not change. No live models were called. The frontend,
API and local isolated preview remain available. Keep #124 open until the host
runner/fencing, immutable storage/publication/downloads, real Temporal recovery
and Releases UI/end-to-end play acceptance are complete.

See the [operator runbook](../runbooks/narrative-builder-preparation.md) and
[focused release design](../superpowers/specs/2026-10-30-narrative-releases-design.md).

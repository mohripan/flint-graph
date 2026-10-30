# Explicit Linux narrative builder preparation

This operator tool prepares the trusted #124 engine image. It does not enable
release requests, start a worker or publish artifacts. Ordinary application
startup and jobs never download engines, install packages or build/pull images.
The source-export Windows toolchain remains separately pinned and unchanged.

## Inputs and preparation

Use the [official4.7.2 release](https://github.com/godotengine/godot-builds/releases/tag/4.7.2-stable)
Linux x86_64 engine and the single-threaded web templates. Verify the archive's
SHA-256 and SHA-512 against `ops/narrative/toolchain-linux.json` before extracting
only its named regular engine file. The preparation tool independently verifies
the extracted engine and both templates against pinned SHA-256 values. It does
not fetch or extract archives. Do not point it at an unreviewed executable.

From the repository root, choose a new output directory whose parent exists:

```powershell
uv run python tools/narrative/prepare_builder.py --engine notes/toolchains/godot-4.7.2/linux/Godot_v4.7.2-stable_linux.x86_64 --templates notes/toolchains/godot-4.7.2/templates --output notes/my-new-builder-context
```

Without `--build`, this only writes a fresh context. It never overwrites an
existing directory. The context includes only verified binaries/templates, the
trusted child, the explicit Dockerfile and runtime hashes. Copied bytes are
rechecked before a toolchain receipt is issued. Preparation failure retains the
new partial context without claiming success.

To opt into image construction, use another new destination and append `--build`.
This operator step uses the immutable Python base digest and installs distribution
fontconfig support. Resolved distribution packages are bound by the final image
ID; the recipe/input identity and final image identity are recorded separately.
No creator source, API credentials, provider settings or Docker socket enters the
image. `COPY` instructions enumerate specific files. The template directory needs
execute permission for UID10001 as well as readable archive files.

The resulting `toolchain.json` records a SHA-256 over pinned engine/template/base
metadata, the exact child/recipe bytes and trusted runtime hashes. The image has
the same toolchain label; use its recorded immutable `sha256:...` ID with
`--pull=never`. A mutable tag is insufficient. Do not upgrade an existing release
identity in place. Preserve the operator receipt and the image needed by accepted
queued releases; later retries must use that original identity.

## Trusted child protocol

The image entrypoint has fixed `/input`, `/scratch`, `/opt/godot` and template
paths. The future trusted worker mounts only a newly prepared input directory
read-only and launches the bounded nonroot/network-none child. It passes no
creator command, script path, environment file or credentials.

The child checks a closed manifest, hashes every known input and independently
checks scripts/runtime files against image-owned hashes. It copies only the
known nineteen files into tmpfs, then runs fixed headless import and Web export
commands. Template paths change only inside scratch; downloadable source should
retain the original editable export instructions.

Each engine stage has a90-second deadline. Output is drained in bounded chunks,
with a small marker window and no retained raw logs. Nonblocking pipes prevent
stdout-inheriting descendants from bypassing the deadline; Linux process-group
cleanup stops remaining engine descendants. PID1 has a separate180-second watchdog
covering build and artifact retrieval even when its host worker disappears.

`/scratch/status.json` is atomically replaced with either a safe failed code or a
complete seven-file size/hash inventory. No source, host path or raw diagnostic
enters that response. The fixed `python /opt/build_child.py archive` command emits
only those known regular web files as USTAR. The host must still enforce its own
bounded decoder, cancellation/deadlines, fence ownership and cleanup. Child status
alone never authorizes publication. Final web distributions also need their
notices/licenses; the seven generated files are not the final release manifest.

## Opt-in qualification

Read the image and toolchain hash from the newly prepared receipt. Set these only
in the qualification shell; do not enable the ordinary API from a probe receipt:

```powershell
$env:FLINT_GRAPH_NARRATIVE_BUILDER_IMAGE='sha256:<prepared-image-id>'
$env:FLINT_GRAPH_NARRATIVE_BUILDER_TOOLCHAIN='<toolchain-sha256>'
uv run pytest tests/integration/test_narrative_build_child_live.py -q --tb=short
```

The two tests export an original text fixture and reject a changed script even
with an updated input manifest. They inspect actual network/root/user/resource/
mount settings and a synthetic host-secret canary, decode the real USTAR stream,
verify file hashes and exercise ZIP output. Optional
`FLINT_GRAPH_NARRATIVE_BUILD_EVIDENCE_DIR` must name a new directory under an
existing parent; it retains owned proof ZIPs and a receipt for operator inspection.
The ZIPs are qualification outputs, not published artifacts or public URLs.

For the additional actual three-minute absent-supervisor check:

```powershell
$env:FLINT_GRAPH_NARRATIVE_BUILDER_WATCHDOG_LIVE='1'
uv run pytest tests/integration/test_narrative_build_watchdog_live.py -q --tb=short
```

It requires exit124 at approximately180 seconds without a host stop, and verifies
the child was not OOM-killed. Each test cleans up only its labeled owned container.
Missing opt-in settings skip the native tests; they never select a default user
image/service. Keep PostgreSQL publication, storage, Temporal and UI acceptance
separate until their actual end-to-end proofs pass.

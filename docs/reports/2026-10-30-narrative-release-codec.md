# Narrative release artifact codec qualification

Scope: the transport/ZIP boundary in #124, not a completed release builder.
The ledger/lifecycle reports remain authoritative for currently available APIs.

`read_child_files` accepts a fixed flat USTAR inventory with checked 512-byte
headers. It rejects unsupported formats/extended headers, links, sparse/special
entries, unexpected paths, duplicate files, malformed padding/trailers and missing
files. Per-file (50 MiB), aggregate (64 MiB), wire (72 MiB) and count (32) bounds
apply before payload allocation/read. Read requests are at most 64 KiB and a
single bounded accumulator avoids retaining one object per short read. No archive
metadata is extracted onto the host filesystem. The future runner must enforce
deadlines and terminate its owned retrieval process/container on failure.

`make_artifact_zip` accepts bounded bytes under portable relative paths, rejects
case collisions and files shadowing another file's parent directory, and emits
sorted entries with fixed timestamps and regular0644 modes. Uncompressed budgets
and a separate64 MiB encoded-output cap apply. It discovers no host files and
includes no filesystem metadata. Equal input/compressor versions produce equal
bytes; this does not promise engine-output reproducibility across hosts.

The same review agent found short-read memory amplification in the first decoder:
a256 KiB payload returned one byte per read retained23,547,408 bytes. A public
regression now requires less than4 MiB and passes with bounded accumulation.
Tests also first demonstrated the unsupported GNU-header and ZIP parent-shadow
gaps, then passed after fixes. Review found no remaining material codec blocker.

## Actual transport proof

A fresh owned nonroot Docker fixture wrote15 trusted bytes into bounded tmpfs.
A fixed in-child USTAR command streamed the file into the new decoder, then the
ZIP writer encoded the validated mapping. Effective inspection verified network
`none`, read-only root, UID/GID10001, dropped capabilities, no-new-privileges,
128 MiB memory/equal swap, oneCPU,64 PIDs, no host binds/devices and1 MiB tmpfs.
The owned container was removed after checking its ownership label.
[Receipt](evidence/narrative-release-codec-2026-10-30/transport-proof.json).

This proves a fixed transport fixture. It does not qualify engine execution,
stream deadlines, worker recovery, publication or authorized downloads. Docker's
copy endpoint cannot read tmpfs output, so the designed runner uses a fixed trusted
`docker exec` archiver; the host never blindly extracts a Docker copy archive.

## Verification

Passed:

- `uv run pytest tests/unit/test_narrative_release_artifacts.py -q --tb=short`:
  49 passed, including malformed entries, early size rejection, short reads,
  bounded zero trailers, checksums, path ambiguity and ZIP metadata/output caps.
- `uv run pytest -q --tb=short`:1296 passed,48 skipped in180.37 seconds.
  Skips are existing opt-in service/native fixtures and backend-specific parameters.
- `uv run ruff check .`; `uv run mypy` (182 source files); `uv lock --check`.
- Deterministic Acme evaluation command from `AGENTS.md`, unchanged quality gate.
- `FLINT_GRAPH_ENV=test uv run alembic upgrade head --sql`:1212 lines through0018.
- `docker compose config --quiet`; `git diff --check`.
- Explicit ignored operator probe `uv run python notes/qualify-release-codec.py`:
  real Docker transport, effective boundary inspection, ZIP receipt and owned cleanup.

Frontend/browser and native PostgreSQL matrices were not repeated for this pure
codec slice; no UI, SQL or service behavior changed. The existing studio remains
available. No providers, private documents or unrelated #109 work were used.
Keep #124 open: engine runner, object store/publication, Temporal integration and
Releases UI/end-to-end download/play qualification remain required.

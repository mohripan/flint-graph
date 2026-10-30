# Immutable release publication and authorized downloads

Scope: #124's private object store, atomic PostgreSQL publication and attachment
API. A real manually driven activity path passed; automatic Temporal/worker
dispatch, startup recovery and Releases UI remain pending. Ordinary API release
creation remains disabled. The preceding runner commit e99b1b0 has green
container smoke41033211942 and CI41033211852 after rerunning a transient Jaeger
backend failure; offline/frontend checks passed on the first attempt.

## Delivered behavior

The new release-specific S3 adapter preserves ingestion storage behavior. It uses
`If-None-Match: *`, independently verifies existing objects on replay and checks
every successful upload with exact HEAD size plus bounded actual bytes/hash.
Object metadata/ETags never authorize content. Reads request at most64 KiB and
stop at expected size plus one sentinel byte; short/extra/wrong bytes fail closed.
Bodies close on success/error; SDK error details are replaced by safe codes.
Caps are64 MiB per ZIP and1 MiB for manifests. SDK factories retain explicit
connect/read timeouts; narrative clients use3 total attempts and close per request.
Canceled SDK I/O may still finish private objects; publication remains separately
fenced and unreachable orphan objects are permitted.

Keys are server-derived from tenant/release/job/execution/kind. Publication locks
release then job, rechecks current ownership/cancellation and requires exactly
three receipts with valid keys, per-kind sizes and a128 MiB aggregate cap. The
canonical host manifest binds the immutable revision/package and compiler/runtime/
Godot/toolchain/image identity to source/web hashes and sizes. It contains no
storage keys, execution token or creator prose. All artifact metadata, completed
event and terminal job state commit together. Rollback exposes none; cancellation
before publication wins; stale owners cannot publish. Successful replay returns
the original artifact IDs in stable kind order without new rows.

Viewer-authorized `GET .../releases/{release_id}/artifacts/{source|web|manifest}`
checks project/tenant/archive access and the complete same-job/same-fence metadata
set before storage. Only fully size/hash-verified bytes become an attachment,
with a fixed safe filename, private/no-store and nosniff. Foreign resources404,
missing bearer401, revoked membership403, incomplete publication404, and missing/
tampered objects503 all fail closed. No public or presigned URL is issued.
Completed release item GET includes compact artifact metadata; collection and
acceptance responses remain summaries, so clients use item GET for availability.

## Actual qualification

An explicitly owned MinIO image
`sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e`
(RELEASE.2025-09-07T16-13-09Z) ran with disposable tmpfs, fresh private credentials
and a loopback dynamic port; no user bucket/volume was used. Native tests proved
conditional replay/conflict, concurrent different uploads with one winner,
same-length tamper rejection and round trips of actual Godot proof ZIPs.
[Store receipt](evidence/narrative-release-publication-2026-10-30/store-proof.json).

A separate loopback API performed17 actual HTTP requests against the owned
PostgreSQL/store. It created an original text-only three-ending Lantern revision,
accepted a release, then a manually invoked scoped claim/loader/runner built it
inside the qualified Linux image. Three verified private uploads stayed404 until
atomic publication. HTTP source/web/manifest downloads matched their hashes and
attachment headers. Foreign workspace selection failed404; late cancellation
reported completed; retry was rejected409; archived access required its explicit
flag. Downloaded source was extracted into a fresh closed inventory and imported
successfully by the independently pinned Windows Godot4.7.2 engine.
[HTTP proof](evidence/narrative-release-publication-2026-10-30/http-proof.json).

The qualification API was stopped after proof. The ordinary frontend/API/local
preview remain available. Proof ZIPs/profile/logs and private fixture metadata stay
under ignored `notes/`; no credentials, raw source or large binaries are committed.
The successful fixture release is archived, with no active queued/running attempt.
This is a disposable qualification database/store, not persistent production data.

## Verification

Passed:

- `uv run pytest tests/unit/test_narrative_artifact_store.py -q --tb=short`:
  19 passed, including lost upload acknowledgment/replay,409 handling, same-length
  conflicts, invalid expectations before SDK calls, short-read memory and safe errors.
- Explicit owned fixture plus actual runner ZIP directory:
  `uv run pytest tests/integration/test_narrative_artifact_store_live.py -q --tb=short`:
  4 passed against real MinIO.
- Explicit owned PostgreSQL URL:
  `uv run pytest tests/integration/test_narrative_release_publication.py tests/integration/test_narrative_release_execution.py tests/integration/test_narrative_releases_api.py -q --tb=short`:
  60 passed,6 backend-specific skips,33 existing Alembic warnings in62.86 seconds.
  Publication-only matrix19 passed/1 SQLite skip includes actual queued publisher/
  canceller locks, rollback, stale fences and signed viewer/foreign/revoked/archive checks.
- `uv run pytest -q --tb=short`:1352 passed,59 skipped in188.40 seconds.
- `uv run ruff check .`; `uv run mypy` (187 files); `uv lock --check`.
- Deterministic Acme evaluation, offline Alembic SQL through0018 (1212 lines),
  `docker compose config --quiet` and `git diff --check`.
- Ignored operator helper `uv run python notes/qualify-publication-http.py`:
  17 real HTTP requests plus actual build/store/publication/download/native import.

Frontend/browser qualification was not repeated because this slice changes no UI;
native engine/container and real HTTP boundaries were exercised as above. No
models or inference servers were called. Review found no material storage or
publication blocker; replay tests caught/fixed unstable artifact-ID ordering.
Keep #124 open until actual Temporal recovery, worker/startup cleanup and Releases
UI/end-to-end acceptance pass.

Primary contracts checked: [S3 conditional PutObject](https://docs.aws.amazon.com/AmazonS3/latest/API/API_PutObject.html)
and [botocore bounded streaming bodies](https://docs.aws.amazon.com/botocore/latest/reference/response.html).

# Release object publication and download operations

The release API/storage slice is implemented; automatic build dispatch and the
Releases UI are still pending. Keep new release creation disabled outside explicit
qualification until the workflow/worker is ready. Manual studio/preview needs no
object store or model. See the [qualification report](../reports/2026-10-30-narrative-release-publication.md).

## Storage and publication

Use the configured private S3-compatible bucket with explicitly bounded SDK
connect/read timeouts. Narrative clients use3 total attempts. The backend must
actually support create-only `If-None-Match: *`; qualify this against the deployed
store. A412 accepts only independently size/hash-verified identical existing
bytes;409 accepts a matching already-visible object or fails safely for retry.
Different bytes never authorize an overwrite. This is distinct from existing
mutable ingestion writes and does not automatically turn on bucket object lock.

The trusted activity derives keys from tenant/release/job/fresh execution UUID and
fixed kind. Upload verified source/web ZIPs, create the canonical release manifest,
then upload that manifest with its explicit1 MiB cap. Each ZIP is at most64 MiB;
all three together must fit128 MiB. Verify uploads before taking PostgreSQL locks.
Perform no network/engine work while holding the publication transaction.

`publish_release_artifacts` independently checks the current active fence/cancel,
receipt namespace/size/hash and exact DB-bound manifest before atomically adding
all metadata, event and terminal state. If commit acknowledgment is lost, reload
authoritative job state: a completed replay returns existing IDs and never rebuilds
or replaces bytes. Failure/cancellation cannot expose partially uploaded objects.
Do not pass private ZIPs/source/object keys through Temporal input/results/heartbeats.

PostgreSQL and S3 have no shared transaction. Private orphan objects can remain
after interruption and must not be exposed or mistaken for a successful release.
Retention/sweep may remove only old unreferenced owned attempts after checking
authoritative publication references; broad bucket deletion is not provided here.

## Authorized download behavior

Release item GET is authoritative for artifact availability and supplies kind,
hash, size, safe filename and media type without storage keys. Collection/create/
retry responses are compact summaries. A completed status alone is insufficient
to invent artifact metadata on the client.

Downloads use the ordinary authenticated workspace selector and are authorized on
every request. Viewer+ can download; foreign project/release resources404, revoked
membership403 and missing OIDC bearer401. Archived projects need explicit
`include_archived=true`. Request artifacts through the API with auth headers;
never expose a long-lived public/presigned store URL or navigate application-origin
HTML from model/build output.

The API requires all three immutable same-job/same-fence metadata records, then
checks exact HEAD size plus bounded actual EOF/hash before responding. Attachments
use fixed ASCII names, private/no-store and nosniff. Failed storage/hash checks
return a safe503 without a partial response. Investigate/restore the exact object
from verified backups; do not silently rebuild under the same release identity.
Secrets, source and raw SDK error details must not enter ordinary diagnostics.

## Reproducible boundary checks

Default offline tests need no service. For real store qualification, explicitly
provide `FLINT_GRAPH_NARRATIVE_STORE_FIXTURE` pointing to an ignored receipt for an
owned disposable loopback MinIO container. Tests verify its label/image/port/bucket
before using credentials and delete only their unique known test keys. Optional
`FLINT_GRAPH_NARRATIVE_ARTIFACT_SOURCE_DIR` points to actual runner proof ZIPs;
`FLINT_GRAPH_NARRATIVE_STORE_EVIDENCE_DIR` must be a new output directory.

```powershell
uv run pytest tests/unit/test_narrative_artifact_store.py -q --tb=short
uv run pytest tests/integration/test_narrative_artifact_store_live.py -q --tb=short
uv run pytest tests/integration/test_narrative_release_publication.py -q --tb=short
```

PostgreSQL cases opt in through `FLINT_GRAPH_NARRATIVE_PG_URL` and use only fresh
owned schemas. They exercise actual queued writer locks and signed membership,
including cancellation/publication ordering and revoked downloads. Socket-level
qualification additionally needs an explicit separate API, the pinned runner and
private store: create an original revision, claim/load/build locally, verify three
uploads, prove404 before commit, publish, then download/hash/import through HTTP.
The current report records that manual activity proof; it does not claim Temporal
or new frontend delivery.

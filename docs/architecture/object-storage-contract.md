# Object-storage contract

## Purpose

Document ingestion will eventually process bytes from object storage. This milestone does not implement upload or object retrieval, but it defines the contract so later parsing work has a stable boundary.

## Existing Fields

`document_versions.object_uri`

- Identifies the immutable raw object for a document version.
- Must refer to the exact bytes the worker should process.
- Is nullable until upload-backed ingestion is implemented.

`document_versions.content_hash`

- Identifies the raw content bytes processed by ingestion.
- Should use a stable digest format, for example `sha256:<hex>`.
- Is nullable until the worker reads actual content.

`document_versions.metadata`

- Stores source-specific attributes that do not belong in first-class columns.
- Must not contain secrets.

## Worker Expectations

Future workers should:

- Read bytes through an object-storage interface, not direct SDK calls inside workflow code.
- Resolve `object_uri` inside activities, not workflows.
- Verify `content_hash` when present.
- Fail the ingestion job with a controlled `job.failed` event when the object is missing, unreadable, too large, or hash-invalid.
- Treat object bytes as immutable for the lifetime of a document version.

## URI Expectations

Allowed URI schemes are not finalized. The first real implementation should choose one local-development scheme and one production scheme, for example:

- `file://...` or `local://...` for local tests
- `s3://bucket/key` for S3-compatible storage

The selected scheme must be documented before workers parse real content.

## Security Notes

- Object URIs are internal storage references, not user-controlled download URLs.
- Workers must not follow arbitrary external URLs as object URIs.
- Upload authorization, tenant membership, content scanning, file size limits, and deletion behavior are future production-hardening work.

## Current Limitation

The current ingestion worker is a stub. It validates workflow dispatch and job transitions, but it does not read `object_uri`, compute `content_hash`, parse documents, create chunks, write embeddings, or mutate a graph.

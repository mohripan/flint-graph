# Milestone 01: Control-plane foundation

## Outcome

The API can create a tenant, register a document, allocate an immutable document version, queue an ingestion job, and expose the job's event history. The slice is intentionally complete at the control-plane level and intentionally does not process document content yet.

## Concepts demonstrated

### Request-scoped transaction ownership

The database dependency owns commit and rollback for the whole request. Application services flush their changes but do not independently commit. This prevents one service from committing half of a larger operation and avoids conflicts with SQLAlchemy's automatic transaction start.

A nested transaction (savepoint) is used where an expected uniqueness race may occur. This lets the application recover from an idempotency or uniqueness conflict without corrupting the surrounding request transaction.

### Immutable document versions

A `Document` is the stable logical identity. Every ingestion attempt creates a `DocumentVersion`. Later stages will attach raw artifacts, parsing results, chunks, extractions, embeddings, and graph mutations to that version.

This makes reprocessing, rollback, provenance, and deletion tractable. We never silently overwrite the evidence behind an answer.

Each ingestion job owns exactly one document version, and each document version can have at most one ingestion job. The database migration and ORM model both declare this uniqueness invariant so retry-safe job creation cannot accidentally attach multiple jobs to the same version.

### Idempotent job creation

Clients supply an `Idempotency-Key`. Repeating the same request for the same tenant and document returns the original job. Reusing the key for a different document produces a conflict.

The database uniqueness constraint is the final authority. Application-level checks improve the common path, but correctness does not depend on a race-prone "check then insert" alone.

### Version allocation under a row lock

`Document.next_version_number` is read and incremented while the document row is locked. Concurrent ingestion requests for the same document therefore cannot allocate the same version number in PostgreSQL.

SQLite is used only for fast integration tests and does not reproduce PostgreSQL row-lock behavior. A PostgreSQL concurrency test will be added with the ingestion workflow milestone.

### Tenant-safe lookup behavior

Tenant-scoped endpoints include the tenant in every lookup. A resource belonging to another tenant is returned as not found, preventing resource-existence disclosure.

This is only a data-access invariant. The current `X-Tenant-ID` header is not an authentication mechanism.

### Problem Details and request correlation

Errors use `application/problem+json` with stable error URNs. Every response gets an `X-Request-ID`, and the same ID appears in error bodies and structured logs.

## Exercises worth doing manually

1. Submit the same ingestion request twice and confirm that the job ID is unchanged.
2. Submit a new idempotency key and confirm that the document version increments.
3. Attempt to access a document through another tenant and inspect the 404 response.
4. Send a URL document without `source_uri` and inspect the validation Problem Details response.
5. Open Grafana and locate the API trace for one request.

## Known gaps

- Tenant creation is not protected by an administrative identity.
- `X-Tenant-ID` is routing context, not authorization.
- No outbox or workflow dispatch exists yet; jobs remain queued.
- SQLite tests do not validate PostgreSQL locking semantics.
- Metrics and log export are not configured yet; the first observability slice focuses on traces.
- No object storage or upload protocol exists yet.

## Exit criteria

- Ruff passes.
- Ruff formatting check passes.
- Mypy strict mode passes.
- Integration and unit tests pass.
- Alembic can render the PostgreSQL migration offline.
- Docker Compose defines the API, migration job, PostgreSQL, and local OpenTelemetry backend.

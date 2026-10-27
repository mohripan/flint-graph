# Narrative project and revision API

M31 / #122, migration **0017_narrative_projects**. Projects organize authored
text-only games; revisions are immutable complete source snapshots compatible
with M30. This boundary runs without models, searchable documents, ingestion,
Temporal, Neo4j, OpenSearch or object storage. The editor and release/build APIs
are separate #123/#124 work.

## Authorization and endpoints

Use existing OIDC bearer authentication and `X-Tenant-ID` workspace membership.
The header alone is never authentication. Local dev auth retains its documented
local behavior. Viewer reads; member/admin/owner creates and saves; admin/owner
archives/restores. After workspace authorization, foreign projects/revisions/base
references/cursors return 404. Revoked memberships lose access on subsequent
requests.

| Endpoint under `/v1/narrative/projects` | Behavior |
| --- | --- |
| `POST ""` | `{name, idempotency_key}` creates project plus its first playable English revision; 201 |
| `GET ""` | Bounded project metadata list; `limit=1..100`, `before_id`, `include_archived` |
| `GET /{project_id}` | Project metadata and head; archived reads require `include_archived=true` |
| `POST /{project_id}/revisions` | Explicit base/key plus strict source string/notices; 201 accepted or persisted 409 conflict |
| `GET /{project_id}/revisions` | Descending revision sequence, compact metadata without source/notices; bounded limit/cursor |
| `GET /{project_id}/revisions/{revision_id}` | Full immutable snapshot; archived reads require explicit flag |
| `POST /{project_id}/archive` | `{base_revision_id, archived: bool}`; archive/restore under the head lock |

Project `name` is a 1..200 character organization label, distinct from the authored
story title. Creation has an original short line and ending with no assets and
empty notices; it does not assert a license/ownership certification. Project
renaming and additional language setup can follow in editor work.

## Saving and recovery

A revision write sends:

```json
{
  "base_revision_id": "<UUID of the revision being edited>",
  "idempotency_key": "<fresh UUID for this save, retained for retry>",
  "story_json": "<complete authored story JSON as a string>",
  "notices": "<UTF-8 author/content notices>"
}
```

The source string is intentional: duplicate keys and numeric syntax survive to
the strict M30 parser. Raw and canonical story are capped at 5 MiB, notices at
1 MiB of UTF-8; type/reference/depth/text/condition limits apply. No implicit
booleans/integers, NUL/surrogates, executable fields or asset/remote-path intake.
Hosted source currently requires an empty asset declaration. Local M30 PNG
packages remain supported; hosted uploads/references require #128's design.
Validation failures expose safe code/location diagnostics and preserve the head.

Each revision records its UUID, project/workspace, positive sequence, parent,
observed head, conflict status, package hash, author and creation time. Source
and notices preserve the hash identity and cannot be edited through the API.
Repeated identical packages may share a content hash while retaining distinct
revision identities. Revision lists and their cursor lookups avoid loading prose.

Under a project row lock, a matching base appends and advances the head. An older
base appends a conflict revision and preserves the head. The 409 problem body
contains `errors[0].conflict_revision_id` and `observed_head_revision_id`; the
snapshot and privacy-safe audit have already committed. Fetch that revision to
recover the exact draft. Clients keep unsaved local work until acknowledgment and
must never silently discard or overwrite either branch. No automatic merge exists.

Keys are scoped per workspace for project creation and per project for revisions.
Equivalent project names normalize surrounding whitespace; revision fingerprints
use canonical package hash plus base, so formatting-only retries match. Reuse with
different work returns 409 without mutation. Exact conflict retries return the
original recovery result even if the head later advances. Archived projects reject
new saves, while already-recorded idempotent outcomes remain replayable.

Archive/restore requires the current head and the same project lock. It preserves
history and is idempotent for the same state. There is no hard-delete endpoint,
retention cleanup, release execution or automatic old-save migration.

## Persistence and guardrails

PostgreSQL is authoritative. Composite FKs bind head, parent and observed head to
the same project/workspace; ordinary revision updates/deletes fail at a deployed
trigger. SQLite fixtures enable FKs but do not prove row locks or production
triggers. The actual PG suite applies all migrations under a generated owned
schema and its own qualified version ledger; it cannot silently fall back to a
public schema's `alembic_version`.

Narrative mutations commit inside a safe persistence boundary. SQLAlchemy
query/flush/commit failures return a generic 503 advising retry with the same key;
raw driver exceptions/inserted prose are not logged or returned. The application
engine also hides SQL parameters. Audit project creation, accepted/conflict saves
and archive/restore in the same transaction, with IDs/sequence/hash only.

Before FastAPI parses narrative bodies, ASGI middleware coalesces at most the
smaller of the configured general request limit and **16 MiB**. Missing, false or
chunked lengths do not bypass it. Empty frames consume no retained per-frame
objects, and oversized streams are not drained. Decoded source limits still apply.

When enabled, the existing memory limiter uses a single narrative route prefix,
canonical workspace UUID and normalized credential identity. OIDC ignores dev
identity headers; dev mode uses the actual configured/default subject. Keys hash
credentials. `FLINT_GRAPH_NARRATIVE_RATE_LIMIT_MAX_BUCKETS` defaults to **10000**
(1..100000); capacity rejects new identities rather than evicting active buckets,
and expired entries are swept at bounded frequency. This is a process-local,
per-credential coarse guard, not a distributed per-user quota or authentication.
It supplements the existing deployment/gateway boundary.

See [ADR 0036](../adr/0036-immutable-authored-revisions-and-recoverable-conflicts.md)
and [real verification](../reports/2026-10-27-narrative-projects.md).

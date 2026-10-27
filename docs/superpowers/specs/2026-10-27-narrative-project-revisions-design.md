# Narrative projects and immutable revisions

Scope: M31 #122. The user approved the narrative studio direction and autonomous
issue-by-issue continuation, including one review agent. This focused design
extends the completed M30 package/runtime boundary; it does not implement the
editor, hosted builds or AI generation. Its implementation proceeds under that
standing authorization.

## Decision and alternatives

Use PostgreSQL projects with append-only canonical source revisions and explicit
optimistic concurrency. A mutable JSON document is simpler but loses the exact
source behind previews/releases and makes concurrent edits destructive. Putting
every small text draft in object storage adds distributed publication failure
without helping this first boundary. Keep bounded canonical story/notices in
PostgreSQL now; attach immutable asset objects through the later asset-library
design rather than storing binaries in JSON.

A project is a workspace-owned named editing container. A revision is a complete
validated package snapshot, with parent, author, sequence, canonical source,
notices and the same M30 content hash. The current head is a project pointer;
previous accepted revisions and conflict revisions remain unchanged. No revision
update/delete API is exposed. PostgreSQL migrations enforce immutable revision
rows against ordinary SQL updates/deletes; database owners can still change DDL.

## First slice and content boundary

Create a blank playable project without models, searchable corpus, ingestion,
Temporal, Neo4j, OpenSearch or object storage. Its initial English story has a
short original line and ending, no characters/variables/assets, and empty notices.
Creation accepts a 1..200 character project `name` and an idempotency UUID.
The project name is organization metadata, separate from the authored story title.
Renaming organization metadata and other languages can follow in editor work.

Revision writes accept `base_revision_id`, `idempotency_key`, `story_json` as a
string and `notices` as a string. A source string preserves duplicate keys and
numeric syntax for M30's strict parser, unlike an already-decoded generic JSON
object. Apply byte/depth/text/type/reference limits, canonicalize after validation,
and compute the existing package hash. Bound raw and canonical story to 5 MiB
and UTF-8 notices to 1 MiB. Reject NUL, surrogates and executable fields.

This first text-authoring API requires an empty asset declaration. M30 local
packages/source export still support PNGs. The hosted asset upload/reference/
approval boundary is #128; accepting arbitrary filesystem paths, asset URLs or
base64 binaries here would bypass that design. The frontend can create and edit
text-only games before asset production arrives. Reuse a pure in-memory validated
text-package constructor; do not write untrusted source into server directories.

## Persistence and consistent references

Add migration `0017_narrative_projects` after the conversation ledger:

- `narrative_projects`: UUID, tenant UUID, name, creation idempotency UUID and
  fingerprint, head revision UUID, positive next revision number, archived time,
  created/updated times. Unique `(tenant_id, creation_key)` and `(id, tenant_id)`.
- `narrative_revisions`: UUID, tenant/project UUIDs, positive sequence, parent
  revision UUID, observed head UUID, conflict boolean, write idempotency UUID and
  fingerprint, canonical story text, notices text, package hash, author user UUID,
  created time. Unique `(project_id, revision_number)`, `(project_id, key)` and
  `(id, project_id, tenant_id)`.

Composite foreign keys constrain every revision parent/observed head and project
head to the same project and workspace. Revision/project/user references restrict
deletion; projects are archived rather than hard-deleted. The head reference is
nullable during initial transactional construction, then set before the create
request commits. Every API-created committed project has its first revision.
Immutable row triggers are installed by the PostgreSQL migration, not assumed
from SQLite metadata-only tests. No migration rewrites existing application data.

## Transactions, retries and conflicts

Project creation briefly locks the authorized workspace row, checks its scoped
idempotency key/fingerprint, then creates project, revision one, head and audit
record in one transaction. Equivalent retries return the same project identity;
reuse with different name returns 409. Responses describe the project's current
state, so its head may have advanced since the first create response.

Revision writes lock the scoped project row, resolve the base under that project,
and check idempotency before allocating a sequence. Foreign project/base references
return 404. Exact semantic retries (canonical package hash plus base) return the
same immutable revision; key reuse for different work returns 409 without mutation.

If the base equals the head, append an accepted revision and advance the head.
If the base is older, append a conflict revision with that parent and observed
head, increment the sequence, preserve the head, and return **409** containing the
saved conflict revision ID and observed current head ID. This outcome must commit
its revision/audit transaction: return an explicit response rather than raising an
exception that the session dependency rolls back. Retrying that same request
replays its original conflict outcome. Clients retain local draft state until
acknowledged and can recover the exact conflict revision later. There is no
automatic merge or mutation of that revision; future adoption makes a new save
against the then-current head. This avoids last-write-wins data loss.

Archive/restore requires admin/owner and an explicit matching head revision.
Serialize it under the same project lock. Archived projects reject new writes;
explicit archived reads retain history. Already-recorded idempotent revision
results remain retrievable. No destructive cleanup or release execution is added.

## API and authorization

Use `/v1/narrative/projects` with existing current-user and tenant dependencies.
`X-Tenant-ID` remains an authorized workspace selector, never authentication.
Viewer reads; member/admin/owner create and save; admin/owner archive/restore.
After workspace authorization, foreign/missing projects and revisions return 404.
Dev auth keeps its documented local behavior; real authorization proof uses signed
OIDC identities with server-side memberships, including revoked memberships.

Endpoints: POST/GET projects, GET project, POST/GET project revisions, GET a scoped
revision, POST project archive. List endpoints are bounded to 1..100 and use
stable ID/sequence cursors resolved under the same workspace/project. Revision
lists return compact metadata; full source is read separately. Project responses
include head and archived state; revision responses include canonical source,
notices, parent/observed head, hash, author and conflict status. No endpoint needs
retrieval readiness or imports/calls a model provider.

Audit create, accepted/conflicted revision and archive/restore in the same
transaction, with IDs, sequence and hashes only. Never put story/notices into
telemetry, audit metadata or exception text. Existing request-size/rate/auth
middleware remains in force. Source validation returns bounded code/location
diagnostics; conflict responses reveal only resources in the authorized project.

## Verification and delivery

Write public API tests before implementation. Offline SQLite tests cover blank
projects, immutable history/hash identity, strict source rejection, bounded lists,
idempotency, conflict recovery, archive lifecycle and OIDC role/tenant isolation.
Enable SQLite foreign keys for this fixture. Do not claim SQLite proves row locks
or deployed PostgreSQL triggers.

Use an explicit owned PostgreSQL database/container, with no production/user data,
to apply real migrations and exercise public endpoints. Verify cross-project FKs,
immutable row triggers, signed identities/roles/revocation, retries and simultaneous
independent sessions submitting the same base. Exactly one accepted head and one
recoverable conflict must result. Record actual migration and HTTP verification;
no live database setting silently targets the existing workspace database.

Run the required regression, lint/type/eval/SQL/Compose gates. Reuse the one
authorized review agent, address findings, commit focused files without co-author
trailers, push and require green CI before closing #122. Preserve unrelated #109
WIP and leave the already-running M30 game preview available. #123 then adds the
editor; #124 handles durable release jobs/artifacts and hosted build isolation.

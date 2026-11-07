# ADR 0073: Project trash and permanent delete

Status: accepted, 2026-11-07

## Context

There was no way to get rid of a project, and tests and experiments pile up on the project list. Deleting
is the one action here that cannot be taken back, so it needs a place to change your mind, a clear warning, and a
guarantee that "deleted" means gone: every row and every file. Three facts make that harder than a `DELETE`:

- Revisions, releases and the assistant's log are immutable by database trigger, on purpose.
- Foreign keys are `RESTRICT`, and some tables point at each other.
- Files live in object storage, which cannot share a transaction with the database.

## Decision

**The trash is the existing `archived_at`.** Moving a project there hides it from lists and every job admission
already refuses it. Nothing is lost, and restoring is immediate. No automatic expiry: a project leaves the trash only
when someone chooses to delete it.

**Delete forever runs in three steps, and repeating it is always safe.**

1. In one transaction: refuse unless the project is in the trash and nothing is queued or running, then set
   `purge_started_at`. From here the project cannot be restored, because some files may already be gone.
2. Delete the files, by listing and deleting under its project prefix and each release's prefix until nothing is left.
3. In one transaction: delete every row.

A failure at step 2 or 3 leaves the project in the trash, showing **Finish deleting**, and trying again carries on.
Files go before rows so that the record of what to clean up outlives the cleanup.

**The tables come from the schema.** `project_tables()` is every `narrative_*` table with a `project_id`, children
first, and `project_loops()` finds what must be cleared to break cycles. A new table is covered without anyone
remembering this code, and a test fails if a table reaches a project some other way. `RUNNING_WORK` is held to the
schema the same way.

**Immutable tables keep refusing.** Their triggers now allow one thing: a `DELETE` of a row whose own project has
`purge_started_at` set. Updates are always refused, and other projects' rows are unaffected. A setting scoped to
the transaction would have been the obvious alternative, but it is invisible afterwards and SQLite has no equivalent,
so the ordinary test run could not have exercised it. The rule rests on durable state instead.

Revisions cannot be updated and always point at older ones, so they are deleted newest first.

**Kept on purpose:** the credit ledger, usage charges and audit trail. They belong to the person rather than the
story, and hold only IDs. Credits spent are not refunded, and the warning says so.

**Permissions:** moving to the trash, restoring and deleting need workspace admin or owner, as archiving already did.
Renaming needs member. The assistant cannot do any of this; it stays a human decision in the Studio.

## Consequences

- A project with a stuck queued job cannot be deleted until that job ends. The creator can restore the project, cancel
  the job and try again. Cancelling on their behalf would need every job type's cancellation to run here.
- Deployment: the API's object store credentials now need `s3:ListBucket` and `s3:DeleteObject` on this bucket's
  `tenants/*/narrative/` keys. Voice references already needed delete.
- With bucket versioning switched on, deleted objects would leave old versions behind. The runbook does not turn it
  on; an operator who does must add a lifecycle rule.
- Games already downloaded keep working. Their release downloads from the Studio stop.
- A job cancelled moments before deletion might, in a narrow race, finish writing a file after the listing has passed.
  It would be private and unreachable. Only re-listing later could find it; this is accepted.

# M31 project/revision implementation plan

Focused scope and authorization: [design](../specs/2026-10-27-narrative-project-revisions-design.md),
GitHub #122. Continue automatically under the user's standing instruction.

1. Add failing API/content tests for a blank text project, append-only saves,
   exact retries, preserved stale conflicts and invalid/foreign source references.
2. Add the bounded in-memory text-package constructor, project/revision SQLAlchemy
   models and PostgreSQL migration with composite FKs and immutable-row triggers.
3. Implement scoped row-locked services, role-gated routes and privacy-safe audits.
   Conflict responses must commit recoverable work rather than roll it back.
4. Add signed-OIDC authorization/archive/pagination tests and actual PostgreSQL
   migration/FK/immutability/concurrent-update proof in an owned isolated database.
5. Run focused and full required gates, review through the existing review agent,
   document actual behavior/limits/commands, commit/push and close only after CI.
6. Continue #123's editor design after this persistence foundation is delivered.

No hosted asset upload, remote code, model inference, release build service or
existing-data migration is included. Preserve #109 WIP and the live M30 preview.

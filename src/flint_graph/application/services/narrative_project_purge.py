"""Deleting a project forever, once it is in the trash (ADR 0073).

The tables are read from the schema, so a new table that holds a project's rows is covered
without anyone having to remember this file. Files go first and rows last: a failure in between
leaves the project in the trash, where trying again finishes the job.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Table, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.schema import sort_tables

import flint_graph.infrastructure.db.models  # noqa: F401 - Registers every table in the metadata.
from flint_graph.application.services.audit import AuditActor, record_audit_event
from flint_graph.application.services.narrative_projects import get_project
from flint_graph.domain.enums import AuditAction
from flint_graph.domain.errors import ConflictError
from flint_graph.infrastructure.db.base import Base
from flint_graph.infrastructure.db.narrative_models import NarrativeProject

# Each kind of job that can be queued or running, and how to speak of it. A test holds this list
# to the schema. Deleting under a running job could leave files behind with nothing to find them.
RUNNING_WORK = (
    ("narrative_assistant_turns", "assistant reply", "assistant replies"),
    ("narrative_image_jobs", "picture job", "picture jobs"),
    ("narrative_voice_jobs", "voice job", "voice jobs"),
    ("narrative_music_jobs", "music job", "music jobs"),
    ("narrative_style_jobs", "training run", "training runs"),
    ("narrative_release_jobs", "release build", "release builds"),
)


def project_tables() -> list[Table]:
    """Every table holding a project's rows, each before anything it points to."""
    tables = [
        table
        for table in Base.metadata.tables.values()
        if table.name.startswith("narrative_") and "project_id" in table.c
    ]
    return list(reversed(sort_tables(tables)))


def project_loops() -> list[tuple[Table, str]]:
    """Rows that point at each other, or at rows of their own table, as (table, column). The column
    is the one part of such a key that can be empty, and clearing it lets the rows be deleted.

    Revisions are the exception: they can never be updated, and only ever point at older ones, so
    they are deleted newest first instead.
    """
    loops: list[tuple[Table, str]] = []
    for table in project_tables():
        if table.name == "narrative_revisions":
            continue
        for constraint in table.foreign_key_constraints:
            if constraint.use_alter or constraint.referred_table is table:
                loops.extend(
                    (table, name) for name in constraint.column_keys if table.c[name].nullable
                )
    return loops


def _table(name: str) -> Table:
    return Base.metadata.tables[name]


async def _count(session: AsyncSession, name: str, tenant_id: UUID, project_id: UUID) -> int:
    table = _table(name)
    return int(
        await session.scalar(
            select(func.count())
            .select_from(table)
            .where(table.c.tenant_id == tenant_id, table.c.project_id == project_id)
        )
        or 0
    )


async def _working(session: AsyncSession, tenant_id: UUID, project_id: UUID) -> tuple[str, ...]:
    found = []
    for name, one, many in RUNNING_WORK:
        table = _table(name)
        count = await session.scalar(
            select(func.count())
            .select_from(table)
            .where(
                table.c.tenant_id == tenant_id,
                table.c.project_id == project_id,
                table.c.status.in_(("queued", "running")),
            )
        )
        if count:
            found.append(f"{count} {one if count == 1 else many}")
    return tuple(found)


@dataclass(frozen=True, slots=True)
class ProjectContents:
    revisions: int
    files: int
    characters: int
    conversations: int
    releases: int
    working: tuple[str, ...]


async def project_contents(
    session: AsyncSession, *, tenant_id: UUID, project_id: UUID
) -> ProjectContents:
    """What deleting this project would take with it, for the warning."""
    await get_project(session, tenant_id=tenant_id, project_id=project_id)
    assets = _table("narrative_assets")
    files = await session.scalar(
        select(func.count())
        .select_from(assets)
        .where(
            assets.c.tenant_id == tenant_id,
            assets.c.project_id == project_id,
            assets.c.status != "discarded",
        )
    )
    return ProjectContents(
        revisions=await _count(session, "narrative_revisions", tenant_id, project_id),
        files=int(files or 0),
        characters=await _count(session, "narrative_character_profiles", tenant_id, project_id),
        conversations=await _count(session, "narrative_assistant_threads", tenant_id, project_id),
        releases=await _count(session, "narrative_releases", tenant_id, project_id),
        working=await _working(session, tenant_id, project_id),
    )


async def begin_purge(session: AsyncSession, *, tenant_id: UUID, project_id: UUID) -> list[UUID]:
    """Refuse what must not be deleted, and record the start before any file goes.

    Returns the project's releases, whose files live under their own IDs.
    """
    project = await get_project(
        session, tenant_id=tenant_id, project_id=project_id, for_update=True
    )
    if project.archived_at is None:
        raise ConflictError("Move this project to the trash before deleting it.")
    working = await _working(session, tenant_id, project_id)
    if working:
        raise ConflictError(
            f"This project is still working on {' and '.join(working)}. "
            "Delete it once that has finished."
        )
    if project.purge_started_at is None:
        project.purge_started_at = datetime.now(UTC)
    releases = _table("narrative_releases")
    return list(
        await session.scalars(
            select(releases.c.id).where(
                releases.c.tenant_id == tenant_id, releases.c.project_id == project_id
            )
        )
    )


async def finish_purge(
    session: AsyncSession, *, tenant_id: UUID, project_id: UUID, actor: AuditActor
) -> None:
    """With the files gone, remove every row in one transaction. Credit history and the audit
    trail are kept: they belong to the person and hold only IDs, never story text."""
    project = await get_project(
        session, tenant_id=tenant_id, project_id=project_id, for_update=True
    )
    if project.purge_started_at is None:
        raise ConflictError("Deleting this project has not started.")
    # Revisions, releases and the assistant's log refuse changes, except a delete of rows whose
    # project has purge_started_at set, as this one now does. The project points at its latest
    # revision too, so let go of that first.
    project.head_revision_id = None
    await session.flush()
    for table, column in project_loops():
        await session.execute(
            update(table)
            .where(table.c.tenant_id == tenant_id, table.c.project_id == project_id)
            .values({column: None})
        )
    for table in project_tables():
        mine = (table.c.tenant_id == tenant_id, table.c.project_id == project_id)
        if table.name == "narrative_revisions":
            newest_first = select(table.c.id).where(*mine).order_by(table.c.revision_number.desc())
            for revision_id in list(await session.scalars(newest_first)):
                await session.execute(delete(table).where(*mine, table.c.id == revision_id))
        else:
            await session.execute(delete(table).where(*mine))
    await session.execute(
        delete(NarrativeProject).where(
            NarrativeProject.id == project_id, NarrativeProject.tenant_id == tenant_id
        )
    )
    session.expunge(project)
    await record_audit_event(
        session,
        action=AuditAction.NARRATIVE_PROJECT_PURGED,
        actor=actor,
        tenant_id=tenant_id,
        resource_type="narrative_project",
        resource_id=project_id,
        metadata={},
    )

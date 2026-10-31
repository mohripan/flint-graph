"""Private voice references and their consent records (#175, ADR 0044).

Members record or upload a 5 to 30 s sample and declare whose voice it is: their own,
or a named speaker who gave permission to clone it. The declaration is recorded with
the declarer and time, not verified. References stay private to the project: they
are not story assets, and audit metadata carries identifiers, never the speaker's
name or what they said.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.services.audit import AuditActor, record_audit_event
from flint_graph.application.services.narrative_projects import get_project
from flint_graph.domain.enums import AuditAction
from flint_graph.domain.errors import ConflictError, DomainError, NotFoundError
from flint_graph.infrastructure.db.models import NarrativeVoiceReference
from flint_graph.narrative.voice_models import REFERENCE_TRANSCRIPT_LIMIT
from flint_graph.narrative.voice_references import CONSENTS, ReferenceAudio


def _invalid(detail: str) -> DomainError:
    return DomainError(422, "Invalid voice reference", detail, "invalid-voice-reference")


def clean_declaration(
    *, speaker_name: str, consent: str, confirmed: bool, transcript: str, name: str
) -> tuple[str, str, str | None, str]:
    """The consent declaration and labels a reference is saved with."""
    if consent not in CONSENTS:
        raise _invalid("Say whether this is your voice or a speaker who gave consent.")
    if not confirmed:
        raise _invalid(
            "Confirm that this is your voice, or that the speaker gave you permission to clone it."
        )
    speaker = " ".join(speaker_name.split())
    if not speaker or len(speaker) > 120:
        raise _invalid("Name the speaker (up to 120 characters).")
    spoken = " ".join(transcript.split())
    if len(spoken) > REFERENCE_TRANSCRIPT_LIMIT:
        raise _invalid(f"Keep the transcript to {REFERENCE_TRANSCRIPT_LIMIT} characters.")
    label = " ".join(name.split()) or speaker
    if len(label) > 120:
        raise _invalid("Keep the name to 120 characters.")
    return speaker, consent, spoken or None, label


async def find_active_reference(
    session: AsyncSession, *, tenant_id: UUID, project_id: UUID, sha256: str
) -> NarrativeVoiceReference | None:
    reference: NarrativeVoiceReference | None = await session.scalar(
        select(NarrativeVoiceReference).where(
            NarrativeVoiceReference.tenant_id == tenant_id,
            NarrativeVoiceReference.project_id == project_id,
            NarrativeVoiceReference.sha256 == sha256,
            NarrativeVoiceReference.status == "active",
        )
    )
    return reference


async def check_reference_project(
    session: AsyncSession, *, tenant_id: UUID, project_id: UUID
) -> None:
    project = await get_project(session, tenant_id=tenant_id, project_id=project_id)
    if project.archived_at is not None:
        raise ConflictError("Restore this project before adding voice references.")


async def record_reference(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    reference_id: UUID,
    audio: ReferenceAudio,
    name: str,
    speaker_name: str,
    consent: str,
    transcript: str | None,
    source: str,
    author_user_id: UUID,
    actor: AuditActor,
) -> NarrativeVoiceReference:
    """Persist a reference whose bytes were already stored create-only and verified."""
    await check_reference_project(session, tenant_id=tenant_id, project_id=project_id)
    reference = NarrativeVoiceReference(
        id=reference_id,
        tenant_id=tenant_id,
        project_id=project_id,
        name=name,
        speaker_name=speaker_name,
        consent=consent,
        consent_declared_by_user_id=author_user_id,
        consent_declared_at=datetime.now(UTC),
        transcript=transcript,
        source=source,
        sha256=audio.sha256,
        size_bytes=len(audio.data),
        duration_ms=audio.duration_ms,
        sample_rate=audio.sample_rate,
        channels=audio.channels,
        status="active",
    )
    session.add(reference)
    await session.flush()
    await record_audit_event(
        session,
        tenant_id=tenant_id,
        action=AuditAction.NARRATIVE_VOICE_REFERENCE_CREATED,
        actor=actor,
        resource_type="narrative_voice_reference",
        resource_id=reference.id,
        metadata={"project_id": str(project_id), "consent": consent, "source": source},
    )
    await session.refresh(reference)
    return reference


async def list_references(
    session: AsyncSession, *, tenant_id: UUID, project_id: UUID
) -> list[NarrativeVoiceReference]:
    await get_project(session, tenant_id=tenant_id, project_id=project_id)
    return list(
        await session.scalars(
            select(NarrativeVoiceReference)
            .where(
                NarrativeVoiceReference.tenant_id == tenant_id,
                NarrativeVoiceReference.project_id == project_id,
                NarrativeVoiceReference.status == "active",
            )
            .order_by(NarrativeVoiceReference.created_at.desc(), NarrativeVoiceReference.id)
        )
    )


async def get_reference(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    reference_id: UUID,
    active: bool = True,
    lock: bool = False,
) -> NarrativeVoiceReference:
    await get_project(session, tenant_id=tenant_id, project_id=project_id)
    statement = select(NarrativeVoiceReference).where(
        NarrativeVoiceReference.tenant_id == tenant_id,
        NarrativeVoiceReference.project_id == project_id,
        NarrativeVoiceReference.id == reference_id,
    )
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    reference = await session.scalar(statement)
    if reference is None or (active and reference.status != "active"):
        raise NotFoundError("Voice reference was not found.")
    return reference


async def delete_reference(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    reference_id: UUID,
    user_id: UUID,
    actor: AuditActor,
) -> tuple[NarrativeVoiceReference, bool]:
    """Mark a reference deleted; ``True`` when this call deleted it (remove its audio)."""
    reference = await get_reference(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        reference_id=reference_id,
        active=False,
        lock=True,
    )
    if reference.status == "deleted":
        return reference, False
    reference.status = "deleted"
    reference.deleted_at = datetime.now(UTC)
    reference.deleted_by_user_id = user_id
    await session.flush()
    await record_audit_event(
        session,
        tenant_id=tenant_id,
        action=AuditAction.NARRATIVE_VOICE_REFERENCE_DELETED,
        actor=actor,
        resource_type="narrative_voice_reference",
        resource_id=reference.id,
        metadata={"project_id": str(project_id)},
    )
    await session.refresh(reference)
    return reference, True

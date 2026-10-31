"""Private voice references with a consent declaration (#175, ADR 0044).

Only workspace members (not viewers) list, hear, add or delete references, because
a reference is a person's voice. Bytes are checked and stored create-only and
hash-verified before the row is written; deleting removes the audio and keeps the
consent record that earlier clips' provenance names.
"""

import asyncio
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, Response, UploadFile
from pydantic import BaseModel, ConfigDict

from flint_graph.api.dependencies import (
    AuditActorDep,
    CurrentUserDep,
    NarrativeArtifactStoreDep,
    SessionDep,
    TenantMemberDep,
)
from flint_graph.api.routes.narrative import _persist
from flint_graph.application.services.narrative_voice_references import (
    check_reference_project,
    clean_declaration,
    delete_reference,
    find_active_reference,
    get_reference,
    list_references,
    record_reference,
)
from flint_graph.domain.errors import DomainError, PayloadTooLargeError
from flint_graph.infrastructure.db.models import NarrativeVoiceReference
from flint_graph.infrastructure.narrative_artifact_store import (
    ArtifactStoreError,
    voice_reference_object_key,
)
from flint_graph.narrative.values import PackageError
from flint_graph.narrative.voice_references import ReferenceRefused, inspect_reference
from flint_graph.narrative.wav import AUDIO_LIMIT

router = APIRouter(
    prefix="/v1/narrative/projects/{project_id}/voice-references", tags=["narrative"]
)


class ReferenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    speaker_name: str
    consent: str
    consent_declared_by_user_id: UUID
    consent_declared_at: datetime
    transcript: str | None
    source: str
    sha256: str
    size_bytes: int
    duration_ms: int
    sample_rate: int
    channels: int
    status: str
    created_at: datetime
    deleted_at: datetime | None


class ReferenceListResponse(BaseModel):
    references: list[ReferenceResponse]


def _response(reference: NarrativeVoiceReference) -> ReferenceResponse:
    return ReferenceResponse.model_validate(reference)


def _unavailable() -> DomainError:
    return DomainError(
        503, "Service unavailable", "The voice reference is unavailable.", "reference-unavailable"
    )


@router.get("", response_model=ReferenceListResponse)
async def list_references_endpoint(
    project_id: UUID, tenant_id: TenantMemberDep, session: SessionDep
) -> ReferenceListResponse:
    rows = await list_references(session, tenant_id=tenant_id, project_id=project_id)
    return ReferenceListResponse(references=[_response(row) for row in rows])


@router.post("", response_model=ReferenceResponse, status_code=201)
async def add_reference_endpoint(
    project_id: UUID,
    tenant_id: TenantMemberDep,
    current_user: CurrentUserDep,
    session: SessionDep,
    store: NarrativeArtifactStoreDep,
    actor: AuditActorDep,
    response: Response,
    file: Annotated[UploadFile, File()],
    speaker_name: Annotated[str, Form(max_length=400)],
    consent: Annotated[str, Form(max_length=40)],
    consent_confirmed: Annotated[bool, Form()],
    transcript: Annotated[str, Form(max_length=4000)] = "",
    name: Annotated[str, Form(max_length=400)] = "",
    source: Annotated[Literal["upload", "recording"], Form()] = "upload",
) -> ReferenceResponse:
    speaker, kind, spoken, label = clean_declaration(
        speaker_name=speaker_name,
        consent=consent,
        confirmed=consent_confirmed,
        transcript=transcript,
        name=name,
    )
    data = await file.read(AUDIO_LIMIT + 1)
    if len(data) > AUDIO_LIMIT:
        raise PayloadTooLargeError("A voice reference is at most 10 MiB.")
    try:
        audio = await asyncio.to_thread(inspect_reference, data)
    except ReferenceRefused as refused:
        raise DomainError(
            422, "Unusable voice reference", str(refused), "invalid-voice-reference"
        ) from None
    except PackageError:
        raise DomainError(
            422,
            "Unusable voice reference",
            "Upload a 16-bit PCM WAV file (mono or stereo, 16 to 48 kHz).",
            "invalid-voice-reference",
        ) from None
    await check_reference_project(session, tenant_id=tenant_id, project_id=project_id)
    existing = await find_active_reference(
        session, tenant_id=tenant_id, project_id=project_id, sha256=audio.sha256
    )
    if existing is not None:
        response.status_code = 200
        return _response(existing)
    reference_id = uuid4()
    try:
        await store.put_once(
            voice_reference_object_key(
                tenant_id=tenant_id, project_id=project_id, reference_id=reference_id
            ),
            audio.data,
            expected_sha256=audio.sha256,
            content_type="audio/wav",
            max_bytes=AUDIO_LIMIT,
        )
    except (ArtifactStoreError, ValueError):
        raise _unavailable() from None
    reference = await _persist(
        session,
        record_reference(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            reference_id=reference_id,
            audio=audio,
            name=label,
            speaker_name=speaker,
            consent=kind,
            transcript=spoken,
            source=source,
            author_user_id=current_user.user.id,
            actor=actor,
        ),
    )
    return _response(reference)


@router.get("/{reference_id}/content")
async def reference_content(
    project_id: UUID,
    reference_id: UUID,
    tenant_id: TenantMemberDep,
    session: SessionDep,
    store: NarrativeArtifactStoreDep,
) -> Response:
    reference = await get_reference(
        session, tenant_id=tenant_id, project_id=project_id, reference_id=reference_id
    )
    try:
        data = await store.get_verified(
            voice_reference_object_key(
                tenant_id=tenant_id, project_id=project_id, reference_id=reference.id
            ),
            expected_size=reference.size_bytes,
            expected_sha256=reference.sha256,
            max_bytes=AUDIO_LIMIT,
        )
    except (ArtifactStoreError, ValueError):
        raise _unavailable() from None
    return Response(
        content=data,
        media_type="audio/wav",
        headers={
            # A person's voice: never kept in shared or browser caches.
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'inline; filename="reference-{reference.id}.wav"',
        },
    )


@router.delete("/{reference_id}", response_model=ReferenceResponse)
async def delete_reference_endpoint(
    project_id: UUID,
    reference_id: UUID,
    tenant_id: TenantMemberDep,
    current_user: CurrentUserDep,
    session: SessionDep,
    store: NarrativeArtifactStoreDep,
    actor: AuditActorDep,
) -> ReferenceResponse:
    reference, _ = await _persist(
        session,
        delete_reference(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            reference_id=reference_id,
            user_id=current_user.user.id,
            actor=actor,
        ),
    )
    try:
        # Idempotent: repeating the request retries removing the audio.
        await store.delete_reference(
            voice_reference_object_key(
                tenant_id=tenant_id, project_id=project_id, reference_id=reference.id
            )
        )
    except (ArtifactStoreError, ValueError):
        raise DomainError(
            503,
            "Service unavailable",
            "The reference is deleted but its audio could not be removed yet. Try again.",
            "reference-unavailable",
        ) from None
    return _response(reference)

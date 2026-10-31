"""Character voices, voice models and local voice jobs (ADR 0043, ADR 0045).

Viewers read; members choose voices, accept model licenses for themselves and start,
list or cancel jobs. Jobs are queued here and run later in the opt-in voice worker;
clips arrive as candidates. The catalog offers only models installed on this server,
with licenses and capabilities from code.
"""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Path, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from flint_graph.api.dependencies import (
    AuditActorDep,
    CurrentUserDep,
    SessionDep,
    SettingsDep,
    TenantIdDep,
    TenantMemberDep,
)
from flint_graph.api.narrative_character_schemas import (
    CHARACTER_ID,
    AssetResponse,
    ProfileResponse,
)
from flint_graph.api.routes.narrative import _persist
from flint_graph.api.routes.narrative_characters import _profile
from flint_graph.application.services.narrative_line_deliveries import (
    clear_delivery,
    list_deliveries,
    set_delivery,
)
from flint_graph.application.services.narrative_voices import (
    accept_license,
    accepted_models,
    cancel_voice_job,
    create_voice_job,
    get_voice_job,
    list_voice_jobs,
    revision_voice_licenses,
    set_character_voice,
)
from flint_graph.config import Settings
from flint_graph.domain.errors import NotFoundError
from flint_graph.infrastructure.db.models import (
    NarrativeAsset,
    NarrativeLineDelivery,
    NarrativeVoiceJob,
)
from flint_graph.narrative.voice_models import (
    DEFAULT_MODEL,
    LICENSES,
    MODELS,
    VoiceModelSpec,
)
from flint_graph.narrative.voices import MAX_ITEMS, TEXT_LIMIT, VOICES

router = APIRouter(prefix="/v1/narrative/projects/{project_id}", tags=["narrative"])
models_router = APIRouter(prefix="/v1/narrative", tags=["narrative"])
CharacterId = Annotated[str, Path(pattern=CHARACTER_ID)]
NodeId = Annotated[str, Path(pattern=CHARACTER_ID)]


def installed_models(settings: Settings) -> frozenset[str]:
    """Kokoro plus the catalog models the operator installed, in catalog order."""
    return frozenset({DEFAULT_MODEL, *settings.narrative_voice_models})


class VoiceOption(BaseModel):
    id: str
    name: str
    accent: str
    gender: str


class StockVoiceOption(BaseModel):
    id: str
    name: str
    description: str


class LicenseSummary(BaseModel):
    id: str
    name: str
    sha256: str
    obligations: Literal["none", "attribution", "player_terms"]
    summary: str


class LicenseText(LicenseSummary):
    text: str
    notice: str
    player_terms: str


class ModelOption(BaseModel):
    id: str
    name: str
    description: str
    default: bool
    cloning: bool
    languages: list[str]
    deliveries: dict[str, Literal["full", "approximate"]]
    tags: list[str]
    watermark: str | None
    reference_transcript: Literal["unused", "optional"]
    stock_voices: list[StockVoiceOption]
    license: LicenseSummary
    # Whether the current creator may generate with it in this workspace.
    accepted: bool


class VoiceCatalog(BaseModel):
    available: bool
    voices: list[VoiceOption]
    models: list[ModelOption]


class VoiceChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_version: int = Field(ge=0)
    voice: str | None = Field(max_length=32)
    model: str | None = Field(default=None, max_length=64)
    reference_id: UUID | None = None


class DeliveryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    emotion: str = Field(default="neutral", max_length=16)
    intensity: float = Field(default=0.5, ge=0, le=1)
    tag: str | None = Field(default=None, max_length=16)


class VoiceItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["full", "vocalization"]
    text: str = Field(min_length=1, max_length=TEXT_LIMIT)
    node_id: str | None = Field(default=None, pattern=CHARACTER_ID)
    delivery: DeliveryInput | None = None


class VoiceJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[VoiceItemCreate] = Field(min_length=1, max_length=MAX_ITEMS)
    idempotency_key: UUID
    language: str = Field(default="en", pattern=r"^[a-z]{2}$")


class LicenseAcceptanceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    license_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class LicenseAcceptanceResponse(BaseModel):
    model_id: str
    license_id: str
    license_sha256: str
    accepted_at: datetime


class LineDeliveryResponse(BaseModel):
    node_id: str
    emotion: str
    intensity: float
    tag: str | None


class LineDeliveryList(BaseModel):
    deliveries: list[LineDeliveryResponse]


class CarriedLine(BaseModel):
    node_id: str
    asset: str


class CarriedLicenseResponse(BaseModel):
    id: str
    name: str
    obligations: Literal["none", "attribution", "player_terms"]
    summary: str
    lines: list[CarriedLine]


class CarriedLicenseList(BaseModel):
    licenses: list[CarriedLicenseResponse]
    # Whether players will see a one-time license screen.
    player_terms: bool


class VoiceJobResponse(BaseModel):
    id: UUID
    character_id: str
    voice_model: str
    voice: str | None
    reference_id: UUID | None
    language: str
    speed: float
    status: str
    progress: int
    count: int
    cancel_requested: bool
    error_code: str | None
    items: list[dict[str, Any]]
    model: str | None
    # Library versions and the device: the GPU name or "cpu", plus each clip's device.
    runtime: dict[str, str] | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    assets: list[AssetResponse]


class VoiceJobListResponse(BaseModel):
    jobs: list[VoiceJobResponse]


def voice_job_response(job: NarrativeVoiceJob, assets: list[NarrativeAsset]) -> VoiceJobResponse:
    return VoiceJobResponse(
        id=job.id,
        character_id=job.character_id,
        voice_model=job.voice_model,
        voice=job.voice,
        reference_id=job.reference_id,
        language=job.language,
        speed=job.speed,
        status=job.status,
        progress=job.progress,
        count=job.count,
        cancel_requested=job.cancel_requested,
        error_code=job.error_code,
        items=list(job.items),
        model=job.model,
        runtime=job.runtime,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        assets=[AssetResponse.model_validate(asset) for asset in assets],
    )


def _license(spec: VoiceModelSpec) -> LicenseSummary:
    item = spec.license
    return LicenseSummary(
        id=item.id,
        name=item.name,
        sha256=item.sha256,
        obligations=item.obligations,
        summary=item.summary,
    )


def _stock(spec: VoiceModelSpec) -> list[StockVoiceOption]:
    if spec.engine == "kokoro":
        return [
            StockVoiceOption(
                id=voice.id, name=voice.name, description=f"{voice.accent} {voice.gender}"
            )
            for voice in VOICES
        ]
    return [StockVoiceOption(**voice.__dict__) for voice in spec.stock_voices]


@router.get("/voices", response_model=VoiceCatalog)
async def voice_catalog(
    project_id: UUID,
    tenant_id: TenantIdDep,
    settings: SettingsDep,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> VoiceCatalog:
    installed = installed_models(settings)
    accepted = await accepted_models(session, tenant_id=tenant_id, user_id=current_user.user.id)
    return VoiceCatalog(
        available=settings.narrative_voice_generation_enabled,
        voices=[VoiceOption(**voice.__dict__) for voice in VOICES],
        models=[
            ModelOption(
                id=spec.id,
                name=spec.name,
                description=spec.description,
                default=spec.id == DEFAULT_MODEL,
                cloning=spec.cloning,
                languages=list(spec.languages),
                deliveries=dict(spec.deliveries),
                tags=list(spec.tags),
                watermark=spec.watermark,
                reference_transcript=spec.reference_transcript,
                stock_voices=_stock(spec),
                license=_license(spec),
                accepted=spec.license.obligations == "none" or spec.id in accepted,
            )
            for spec in MODELS.values()
            if spec.id in installed
        ],
    )


@models_router.get("/voice-licenses/{license_id}", response_model=LicenseText)
async def voice_license(license_id: str, tenant_id: TenantIdDep) -> LicenseText:
    item = LICENSES.get(license_id)
    if item is None:
        raise NotFoundError("License was not found.")
    return LicenseText(
        id=item.id,
        name=item.name,
        sha256=item.sha256,
        obligations=item.obligations,
        summary=item.summary,
        text=item.text,
        notice=item.notice,
        player_terms=item.player_terms,
    )


@models_router.post(
    "/voice-models/{model_id}/license-acceptance", response_model=LicenseAcceptanceResponse
)
async def accept_voice_license(
    model_id: str,
    payload: LicenseAcceptanceCreate,
    tenant_id: TenantMemberDep,
    current_user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
    actor: AuditActorDep,
) -> LicenseAcceptanceResponse:
    row = await _persist(
        session,
        accept_license(
            session,
            tenant_id=tenant_id,
            user_id=current_user.user.id,
            model_id=model_id,
            license_sha256=payload.license_sha256,
            installed=installed_models(settings),
            actor=actor,
        ),
    )
    return LicenseAcceptanceResponse(
        model_id=row.model_id,
        license_id=row.license_id,
        license_sha256=row.license_sha256,
        accepted_at=row.accepted_at,
    )


@router.get("/revisions/{revision_id}/voice-licenses", response_model=CarriedLicenseList)
async def revision_voice_licenses_endpoint(
    project_id: UUID, revision_id: UUID, tenant_id: TenantIdDep, session: SessionDep
) -> CarriedLicenseList:
    """Before a build: the voice licenses its NOTICES carry and the lines that cause each."""
    carried = await revision_voice_licenses(
        session, tenant_id=tenant_id, project_id=project_id, revision_id=revision_id
    )
    return CarriedLicenseList(
        licenses=[
            CarriedLicenseResponse(
                id=item.license_id,
                name=item.name,
                obligations=item.obligations,
                summary=item.summary,
                lines=[CarriedLine(node_id=node, asset=asset) for node, asset in item.lines],
            )
            for item in carried
        ],
        player_terms=any(item.obligations == "player_terms" for item in carried),
    )


def _delivery(row: NarrativeLineDelivery) -> LineDeliveryResponse:
    return LineDeliveryResponse(
        node_id=row.node_id, emotion=row.emotion, intensity=row.intensity, tag=row.tag
    )


@router.get("/line-deliveries", response_model=LineDeliveryList)
async def list_line_deliveries(
    project_id: UUID, tenant_id: TenantIdDep, session: SessionDep
) -> LineDeliveryList:
    rows = await list_deliveries(session, tenant_id=tenant_id, project_id=project_id)
    return LineDeliveryList(deliveries=[_delivery(row) for row in rows])


@router.put("/line-deliveries/{node_id}", response_model=LineDeliveryResponse)
async def put_line_delivery(
    project_id: UUID,
    node_id: NodeId,
    payload: DeliveryInput,
    tenant_id: TenantMemberDep,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> LineDeliveryResponse:
    row = await _persist(
        session,
        set_delivery(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            node_id=node_id,
            emotion=payload.emotion,
            intensity=payload.intensity,
            tag=payload.tag,
            user_id=current_user.user.id,
        ),
    )
    return _delivery(row)


@router.delete("/line-deliveries/{node_id}", status_code=204)
async def delete_line_delivery(
    project_id: UUID, node_id: NodeId, tenant_id: TenantMemberDep, session: SessionDep
) -> Response:
    await _persist(
        session,
        clear_delivery(session, tenant_id=tenant_id, project_id=project_id, node_id=node_id),
    )
    return Response(status_code=204)


@router.put("/characters/{character_id}/voice", response_model=ProfileResponse)
async def choose_character_voice(
    project_id: UUID,
    character_id: CharacterId,
    payload: VoiceChoice,
    tenant_id: TenantMemberDep,
    current_user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
) -> ProfileResponse:
    row, portrait = await _persist(
        session,
        set_character_voice(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            character_id=character_id,
            base_version=payload.base_version,
            voice=payload.voice,
            author_user_id=current_user.user.id,
            model=payload.model,
            reference_id=payload.reference_id,
            installed=installed_models(settings),
        ),
    )
    return _profile(row, portrait)


@router.post(
    "/characters/{character_id}/voice-jobs", response_model=VoiceJobResponse, status_code=202
)
async def create_character_voice_job(
    project_id: UUID,
    character_id: CharacterId,
    payload: VoiceJobCreate,
    tenant_id: TenantMemberDep,
    current_user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
    actor: AuditActorDep,
) -> VoiceJobResponse:
    job = await _persist(
        session,
        create_voice_job(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            character_id=character_id,
            author_user_id=current_user.user.id,
            items=[item.model_dump() for item in payload.items],
            idempotency_key=payload.idempotency_key,
            actor=actor,
            available=settings.narrative_voice_generation_enabled,
            max_active_jobs=settings.narrative_voice_max_active_jobs_per_workspace,
            installed=installed_models(settings),
            language=payload.language,
        ),
    )
    return voice_job_response(job, [])


@router.get("/voice-jobs", response_model=VoiceJobListResponse)
async def list_voice_jobs_endpoint(
    project_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
    character_id: Annotated[str | None, Query(pattern=CHARACTER_ID)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> VoiceJobListResponse:
    rows = await list_voice_jobs(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        character_id=character_id,
        limit=limit,
    )
    return VoiceJobListResponse(jobs=[voice_job_response(job, assets) for job, assets in rows])


@router.get("/voice-jobs/{job_id}", response_model=VoiceJobResponse)
async def get_voice_job_endpoint(
    project_id: UUID, job_id: UUID, tenant_id: TenantIdDep, session: SessionDep
) -> VoiceJobResponse:
    job, assets = await get_voice_job(
        session, tenant_id=tenant_id, project_id=project_id, job_id=job_id
    )
    return voice_job_response(job, assets)


@router.post("/voice-jobs/{job_id}/cancel", response_model=VoiceJobResponse)
async def cancel_voice_job_endpoint(
    project_id: UUID,
    job_id: UUID,
    tenant_id: TenantMemberDep,
    session: SessionDep,
    actor: AuditActorDep,
) -> VoiceJobResponse:
    job = await _persist(
        session,
        cancel_voice_job(
            session, tenant_id=tenant_id, project_id=project_id, job_id=job_id, actor=actor
        ),
    )
    _, assets = await get_voice_job(
        session, tenant_id=tenant_id, project_id=project_id, job_id=job.id
    )
    return voice_job_response(job, assets)

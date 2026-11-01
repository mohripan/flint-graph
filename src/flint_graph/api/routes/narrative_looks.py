"""Private Studio looks; viewers read, workspace members review and select."""

from functools import lru_cache
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.api.dependencies import (
    AuditActorDep,
    CurrentUserDep,
    NarrativeArtifactStoreDep,
    SessionDep,
    SettingsDep,
    TenantIdDep,
    TenantMemberDep,
)
from flint_graph.api.narrative_character_schemas import (
    CHARACTER_ID,
    AssetResponse,
    ImageJobResponse,
)
from flint_graph.api.routes.narrative import _persist
from flint_graph.api.routes.narrative_characters import job_response
from flint_graph.application.services.narrative_characters import get_asset
from flint_graph.application.services.narrative_look_images import (
    queue_look_expression,
    queue_look_scene,
)
from flint_graph.application.services.narrative_look_reviews import (
    read_review,
    review_candidate,
    write_review,
)
from flint_graph.application.services.narrative_look_tags import record_observation, suggested_tags
from flint_graph.application.services.narrative_looks import (
    create_look,
    get_look,
    queue_look_portrait,
    reference,
    select_look,
    selection,
)
from flint_graph.application.services.narrative_projects import get_project
from flint_graph.infrastructure.db.models import NarrativeAsset, NarrativeImageJob
from flint_graph.infrastructure.db.narrative_look_models import (
    NarrativeCandidateReview,
    NarrativeCharacterLook,
    NarrativeLookJob,
)
from flint_graph.infrastructure.narrative_artifact_store import ArtifactStoreError, asset_object_key
from flint_graph.infrastructure.narrative_look_tagger import LookTagger, unavailable
from flint_graph.narrative.character_bench import CLOTHING_V1, clothing_overlap
from flint_graph.narrative.imagegen import content_policy

router = APIRouter(
    prefix="/v1/narrative/projects/{project_id}/characters/{character_id}/looks", tags=["narrative"]
)
project_router = APIRouter(prefix="/v1/narrative/projects/{project_id}", tags=["narrative"])
CharacterId = Annotated[str, Path(pattern=CHARACTER_ID)]


class LookCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    asset_id: UUID
    identity_tags: list[Annotated[str, Field(max_length=80)]] = Field(max_length=24)
    clothing_tags: list[Annotated[str, Field(max_length=80)]] = Field(max_length=24)
    parent_look_id: UUID | None = None
    base_version: int = Field(ge=0)
    idempotency_key: UUID
    observation_id: UUID | None = None


class LookChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    look_id: UUID | None
    base_version: int = Field(ge=0)


class LookPortrait(BaseModel):
    model_config = ConfigDict(extra="forbid")
    look_id: UUID
    framing: Literal["portrait", "full_body"]
    transparent: StrictBool = False
    hires: StrictBool = False
    count: int = Field(default=4, ge=1, le=4)
    idempotency_key: UUID


class LookExpression(BaseModel):
    model_config = ConfigDict(extra="forbid")
    face_box: list[Annotated[int, Field(ge=0, le=4096)]] = Field(min_length=4, max_length=4)
    expressions: list[Annotated[str, Field(min_length=1, max_length=40)]] = Field(
        min_length=1, max_length=4
    )
    idempotency_key: UUID
    look_id: UUID


class SceneLook(BaseModel):
    model_config = ConfigDict(extra="forbid")
    character_id: str = Field(pattern=CHARACTER_ID)
    look_id: UUID


class LookScene(BaseModel):
    model_config = ConfigDict(extra="forbid")
    characters: list[SceneLook] = Field(min_length=1, max_length=2)
    scene: str = Field(min_length=1, max_length=600)
    count: int = Field(default=4, ge=1, le=4)
    idempotency_key: UUID


class CandidateFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_version: int = Field(ge=0)
    identity: Literal["same", "drifted", "unknown"]
    clothes: Literal["same", "drifted", "unknown"]
    notes: str = Field(default="", max_length=1200)


async def look_response(session: AsyncSession, row: NarrativeCharacterLook) -> dict[str, Any]:
    asset = await get_asset(
        session, tenant_id=row.tenant_id, project_id=row.project_id, asset_id=row.asset_id
    )
    return {
        "id": row.id,
        "tagger_observation": row.tagger_observation,
        "prompt_bundle_sha256": row.prompt_bundle_sha256,
        "policy_sha256": row.policy_sha256,
        "name": row.name,
        "asset": AssetResponse.model_validate(asset),
        "source_sha256": row.source_sha256,
        "identity_tags": row.identity_tags,
        "clothing_tags": row.clothing_tags,
        "character_type": row.character_type,
        "parent_look_id": row.parent_look_id,
        "sha256": row.sha256,
        "created_at": row.created_at,
        "reviewed_by_user_id": row.reviewed_by_user_id,
    }


@router.get("")
async def list_looks_endpoint(
    project_id: UUID, character_id: CharacterId, tenant_id: TenantIdDep, session: SessionDep
) -> dict[str, Any]:
    await get_project(session, tenant_id=tenant_id, project_id=project_id)
    rows = list(
        await session.scalars(
            select(NarrativeCharacterLook)
            .where(
                NarrativeCharacterLook.tenant_id == tenant_id,
                NarrativeCharacterLook.project_id == project_id,
                NarrativeCharacterLook.character_id == character_id,
            )
            .order_by(NarrativeCharacterLook.created_at.desc(), NarrativeCharacterLook.id.desc())
        )
    )
    current = await selection(session, project_id, character_id)
    return {
        "looks": [await look_response(session, row) for row in rows],
        "selection": {
            "version": current.version if current else 0,
            "look_id": current.look_id if current else None,
        },
    }


@router.post("", status_code=201)
async def create_look_endpoint(
    project_id: UUID,
    character_id: CharacterId,
    payload: LookCreate,
    tenant_id: TenantMemberDep,
    current_user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
    actor: AuditActorDep,
) -> dict[str, Any]:
    row = await _persist(
        session,
        create_look(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            character_id=character_id,
            author_user_id=current_user.user.id,
            actor=actor,
            policy=content_policy(settings.narrative_image_content_policy),
            **payload.model_dump(),
        ),
    )
    return await look_response(session, row)


@router.post("/selection")
async def select_look_endpoint(
    project_id: UUID,
    character_id: CharacterId,
    payload: LookChoice,
    tenant_id: TenantMemberDep,
    session: SessionDep,
    actor: AuditActorDep,
) -> dict[str, Any]:
    row = await _persist(
        session,
        select_look(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            character_id=character_id,
            actor=actor,
            **payload.model_dump(),
        ),
    )
    return {"version": row.version, "look_id": row.look_id}


@router.post("/portrait-jobs", status_code=202)
async def look_portrait_endpoint(
    project_id: UUID,
    character_id: CharacterId,
    payload: LookPortrait,
    tenant_id: TenantMemberDep,
    current_user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
    actor: AuditActorDep,
) -> ImageJobResponse:
    job = await _persist(
        session,
        queue_look_portrait(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            character_id=character_id,
            author_user_id=current_user.user.id,
            actor=actor,
            available=settings.narrative_image_generation_enabled,
            max_active_jobs=settings.narrative_image_max_active_jobs_per_workspace,
            policy=content_policy(settings.narrative_image_content_policy),
            **payload.model_dump(),
        ),
    )
    return job_response(job, [])


@router.get("/jobs")
async def look_jobs_endpoint(
    project_id: UUID, character_id: CharacterId, tenant_id: TenantIdDep, session: SessionDep
) -> dict[str, Any]:
    await get_project(session, tenant_id=tenant_id, project_id=project_id)
    jobs = list(
        await session.scalars(
            select(NarrativeImageJob)
            .join(NarrativeLookJob, NarrativeLookJob.job_id == NarrativeImageJob.id)
            .where(
                NarrativeLookJob.tenant_id == tenant_id,
                NarrativeLookJob.project_id == project_id,
                NarrativeLookJob.character_id == character_id,
            )
            .order_by(NarrativeImageJob.created_at.desc(), NarrativeImageJob.id.desc())
            .limit(30)
        )
    )
    result = []
    for job in jobs:
        snapshots = list(
            await session.scalars(select(NarrativeLookJob).where(NarrativeLookJob.job_id == job.id))
        )
        assets = list(
            await session.scalars(
                select(NarrativeAsset)
                .where(NarrativeAsset.job_id == job.id, NarrativeAsset.status != "discarded")
                .order_by(NarrativeAsset.job_index)
            )
        )
        result.append(
            {"job": job_response(job, assets), "looks": [row.snapshot for row in snapshots]}
        )
    return {"jobs": result}


@router.post("/expression-jobs", status_code=202)
async def look_expression_endpoint(
    project_id: UUID,
    character_id: CharacterId,
    payload: LookExpression,
    tenant_id: TenantMemberDep,
    current_user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
    actor: AuditActorDep,
) -> ImageJobResponse:
    job = await _persist(
        session,
        queue_look_expression(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            character_id=character_id,
            author_user_id=current_user.user.id,
            actor=actor,
            available=settings.narrative_image_generation_enabled,
            max_active_jobs=settings.narrative_image_max_active_jobs_per_workspace,
            policy=content_policy(settings.narrative_image_content_policy),
            **payload.model_dump(),
        ),
    )
    return job_response(job, [])


@project_router.post("/look-scene-art-jobs", status_code=202)
async def look_scene_endpoint(
    project_id: UUID,
    payload: LookScene,
    tenant_id: TenantMemberDep,
    current_user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
    actor: AuditActorDep,
) -> ImageJobResponse:
    job = await _persist(
        session,
        queue_look_scene(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            author_user_id=current_user.user.id,
            actor=actor,
            available=settings.narrative_image_generation_enabled,
            max_active_jobs=settings.narrative_image_max_active_jobs_per_workspace,
            policy=content_policy(settings.narrative_image_content_policy),
            **payload.model_dump(),
        ),
    )
    return job_response(job, [])


def feedback_response(row: NarrativeCandidateReview | None) -> dict[str, Any]:
    return {
        "version": row.version if row else 0,
        "identity": row.identity if row else "unknown",
        "clothes": row.clothes if row else "unknown",
        "notes": row.notes if row else "",
        "review_kind": "manual" if row else None,
        "reviewed_by_user_id": row.reviewed_by_user_id if row else None,
    }


@lru_cache(maxsize=4)
def cached_tagger(python: str | None, model_dir: str | None) -> LookTagger:
    return LookTagger(python, model_dir)


def get_look_tagger(settings: SettingsDep) -> LookTagger:
    return cached_tagger(
        settings.narrative_look_tagger_python, settings.narrative_look_tagger_model_dir
    )


class SuggestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: UUID


@router.post("/suggestions")
async def suggest_look_endpoint(
    project_id: UUID,
    character_id: CharacterId,
    payload: SuggestionRequest,
    tenant_id: TenantMemberDep,
    session: SessionDep,
    store: NarrativeArtifactStoreDep,
    settings: SettingsDep,
    tagger: Annotated[LookTagger, Depends(get_look_tagger)],
) -> dict[str, Any]:
    await get_project(session, tenant_id=tenant_id, project_id=project_id)
    asset = await reference(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        character_id=character_id,
        asset_id=payload.asset_id,
    )
    try:
        data = await store.get_verified(
            asset_object_key(
                tenant_id=tenant_id, project_id=project_id, asset_id=asset.id, variant="image"
            ),
            expected_size=asset.size_bytes,
            expected_sha256=asset.sha256,
            max_bytes=8 * 1024 * 1024,
        )
    except (ArtifactStoreError, ValueError):
        raise unavailable(
            "The approved reference image is unavailable. Choose another image."
        ) from None
    result = await tagger.tag(data)
    row = await _persist(
        session,
        record_observation(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            character_id=character_id,
            asset_id=asset.id,
            source_sha256=asset.sha256,
            result=result,
        ),
    )
    identity, clothes = suggested_tags(
        result, content_policy(settings.narrative_image_content_policy)
    )
    return {
        "observation_id": row.id,
        "identity_tags": identity,
        "clothing_tags": clothes,
        "model_manifest_sha256": result["model_manifest_sha256"],
        "tagger_sha256": result["tagger_sha256"],
    }


@router.post("/{look_id}/compare/{asset_id}")
async def compare_tags_endpoint(
    project_id: UUID,
    character_id: CharacterId,
    look_id: UUID,
    asset_id: UUID,
    tenant_id: TenantMemberDep,
    session: SessionDep,
    store: NarrativeArtifactStoreDep,
    tagger: Annotated[LookTagger, Depends(get_look_tagger)],
) -> dict[str, Any]:
    await get_project(session, tenant_id=tenant_id, project_id=project_id)
    look = await get_look(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        character_id=character_id,
        look_id=look_id,
    )
    source = await reference(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        character_id=character_id,
        asset_id=look.asset_id,
    )
    candidate = await review_candidate(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        character_id=character_id,
        look_id=look_id,
        asset_id=asset_id,
    )
    if candidate.provenance.get("ip_adapter") or candidate.provenance.get("references"):
        return {
            "clothing_overlap": None,
            "identity": None,
            "automatic_verdict": None,
            "reference_tags": {},
            "candidate_tags": {},
            "reason": "Compare CG characters visually; "
            "single-person crops are required for tag scores.",
        }
    results = []
    for image in (source, candidate):
        try:
            data = await store.get_verified(
                asset_object_key(
                    tenant_id=tenant_id, project_id=project_id, asset_id=image.id, variant="image"
                ),
                expected_size=image.size_bytes,
                expected_sha256=image.sha256,
                max_bytes=8 * 1024 * 1024,
            )
        except (ArtifactStoreError, ValueError):
            raise unavailable(
                "An image is unavailable. You can still review it manually."
            ) from None
        results.append(await tagger.tag(data))
    reference_row = await record_observation(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        character_id=character_id,
        asset_id=source.id,
        source_sha256=source.sha256,
        result=results[0],
    )
    candidate_row = await record_observation(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        character_id=character_id,
        asset_id=candidate.id,
        source_sha256=candidate.sha256,
        result=results[1],
        approved_only=False,
    )
    await session.commit()
    compatible = results[0]["tagger_sha256"] == results[1]["tagger_sha256"]

    def garments(result: dict[str, Any]) -> dict[str, float]:
        return {
            tag.replace("_", " "): value
            for tag, value in result["general_tags"].items()
            if value >= 0.35
            and not tag.startswith(("no_", "removed_"))
            and tag.rsplit("_", 1)[-1] in CLOTHING_V1
        }

    return {
        "clothing_overlap": clothing_overlap(results[0]["general_tags"], results[1]["general_tags"])
        if compatible
        else None,
        "identity": None,
        "automatic_verdict": None,
        "reference_tags": garments(results[0]),
        "candidate_tags": garments(results[1]),
        "reference_observation_id": reference_row.id,
        "candidate_observation_id": candidate_row.id,
        "tagger_sha256": results[0]["tagger_sha256"],
        "model_manifest_sha256": results[0]["model_manifest_sha256"],
        "taxonomy_version": 1,
        "confidence": 0.35,
        "reason": "Coarse clothing tags only. Colors, trim, occlusion and pose can mislead "
        "this comparison; your review decides.",
    }


@router.get("/{look_id}/reviews/{asset_id}")
async def read_feedback_endpoint(
    project_id: UUID,
    character_id: CharacterId,
    look_id: UUID,
    asset_id: UUID,
    tenant_id: TenantIdDep,
    session: SessionDep,
) -> dict[str, Any]:
    row = await read_review(
        session,
        tenant_id=tenant_id,
        project_id=project_id,
        character_id=character_id,
        look_id=look_id,
        asset_id=asset_id,
    )
    return feedback_response(row)


@project_router.get("/look-reviews")
async def review_flags_endpoint(
    project_id: UUID,
    asset_id: Annotated[list[UUID], Query(max_length=100)],
    tenant_id: TenantIdDep,
    session: SessionDep,
) -> dict[str, Any]:
    await get_project(session, tenant_id=tenant_id, project_id=project_id)
    rows = await session.execute(
        select(NarrativeCandidateReview, NarrativeCharacterLook.name)
        .join(NarrativeCharacterLook, NarrativeCharacterLook.id == NarrativeCandidateReview.look_id)
        .where(
            NarrativeCandidateReview.tenant_id == tenant_id,
            NarrativeCandidateReview.project_id == project_id,
            NarrativeCandidateReview.asset_id.in_(asset_id),
        )
        .order_by(NarrativeCandidateReview.updated_at.desc())
        .limit(1001)
    )
    found = list(rows)
    return {
        "truncated": len(found) > 1000,
        "reviews": [
            {
                "asset_id": row.asset_id,
                "look_id": row.look_id,
                "look_name": name,
                "identity": row.identity,
                "clothes": row.clothes,
            }
            for row, name in found[:1000]
        ],
    }


@router.post("/{look_id}/reviews/{asset_id}")
async def write_feedback_endpoint(
    project_id: UUID,
    character_id: CharacterId,
    look_id: UUID,
    asset_id: UUID,
    payload: CandidateFeedback,
    tenant_id: TenantMemberDep,
    current_user: CurrentUserDep,
    session: SessionDep,
    actor: AuditActorDep,
) -> dict[str, Any]:
    row = await _persist(
        session,
        write_review(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            character_id=character_id,
            look_id=look_id,
            asset_id=asset_id,
            author_user_id=current_user.user.id,
            actor=actor,
            **payload.model_dump(),
        ),
    )
    return feedback_response(row)

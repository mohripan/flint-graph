"""Explicit reviewed training admissions and scoped private version metadata."""

from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flint_graph.application.narrative_image_workflow import ImageJobPayload
from flint_graph.application.services.access import charge_usage
from flint_graph.application.services.narrative_anatomy_reviews import ensure_training_anatomy
from flint_graph.application.services.narrative_projects import get_project
from flint_graph.application.services.outbox import append_outbox_message
from flint_graph.domain.errors import DomainError, NotFoundError
from flint_graph.infrastructure.db.models import NarrativeAsset, Tenant
from flint_graph.infrastructure.db.narrative_style_models import NarrativeStyleJob
from flint_graph.narrative.imagegen import ContentPolicy, clean_appearance
from flint_graph.narrative.values import canonical_json
from flint_graph.prompts.source import current_snapshot, snapshot_async

QUEUED = "narrative.style_queued"
CANCELLED = "narrative.style_cancelled"
WORKFLOW = "NarrativeStyleJobWorkflow"
ACTIVE = ("queued", "running")
RECIPE = {
    "schema": 1,
    "rank": 4,
    "alpha": 4,
    "area": 512**2,
    "max_side": 768,
    "batch": 1,
    "lr": 0.0001,
    "weight_decay": 0.01,
    "optimizer": "AdamW8bit",
    "objective": "flow_matching_uniform",
    "vae": "mode",
    "base_dtype": "bf16",
    "train_dtype": "fp32",
    "checkpointing": True,
    "order": "round_robin",
    "runtime_lock": "stylegen-v1",
}
RECIPE_SHA = sha256(canonical_json(RECIPE)).hexdigest()
REFERENCE_RECIPE = {
    **RECIPE,
    "schema": 2,
    "conditioning": "approved_look_image",
    "reference_preprocess": "fit512_floor16_rgb_white",
    "reference_ids": "time10_target0",
    "reference_vae": "mode_bn_normalized",
    "loss_tokens": "target_only",
    "runtime_lock": "stylegen-reference-v1",
}
REFERENCE_RECIPE_SHA = sha256(canonical_json(REFERENCE_RECIPE)).hexdigest()


def workflow_id(payload: ImageJobPayload) -> str:
    return "narrative-style-" + str(UUID(payload["job_id"]))


async def get_style(
    session: AsyncSession, *, tenant_id: UUID, project_id: UUID, job_id: UUID, lock: bool = False
) -> NarrativeStyleJob:
    statement = select(NarrativeStyleJob).where(
        NarrativeStyleJob.id == job_id,
        NarrativeStyleJob.project_id == project_id,
        NarrativeStyleJob.tenant_id == tenant_id,
    )
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    row = await session.scalar(statement)
    if row is None:
        raise NotFoundError("Style version was not found.")
    return row


def response(row: NarrativeStyleJob) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "name": row.name,
        "status": row.status,
        "progress": row.progress,
        "steps": row.steps,
        "seed": row.seed,
        "images": row.images,
        "dataset_sha256": row.dataset_sha256,
        "model_manifest_sha256": row.model_manifest_sha256,
        "recipe_sha256": row.recipe_sha256,
        "conditioning": "reference" if row.recipe_sha256 == REFERENCE_RECIPE_SHA else "text",
        "weights_sha256": row.weights_sha256,
        "cancel_requested": row.cancel_requested,
        "error_code": row.error_code,
        "losses": row.losses,
        "runtime": row.runtime,
        "tracking_run_id": row.tracking_run_id,
        "created_at": row.created_at.isoformat(),
    }


@snapshot_async
async def queue_style(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    project_id: UUID,
    author_user_id: UUID,
    name: str,
    images: list[dict[str, Any]],
    rights_confirmed: bool,
    steps: int,
    seed: int,
    idempotency_key: UUID,
    available: bool,
    model_manifest_sha256: str | None,
    policy: ContentPolicy,
    character_look: dict[str, Any] | None = None,
    conditioning: str = "text",
    reference_training_available: bool = False,
) -> NarrativeStyleJob:
    if not rights_confirmed:
        raise DomainError(
            422,
            "Training rights required",
            "Confirm rights to train on these images.",
            "style-rights-required",
        )
    await session.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    project = await get_project(
        session, tenant_id=tenant_id, project_id=project_id, for_update=True
    )
    request_hash = sha256(
        canonical_json(
            {
                "name": name,
                **({"conditioning": "reference"} if conditioning == "reference" else {}),
                **(
                    {
                        "character_look": {
                            "character_id": character_look["character_id"],
                            "look_id": str(character_look["look_id"]),
                            "same_look_confirmed": character_look["same_look_confirmed"],
                            "anatomy_reviewed": character_look["anatomy_reviewed"],
                        }
                    }
                    if character_look
                    else {}
                ),
                "images": [
                    {"asset_id": str(i["asset_id"]), "caption": i["caption"]} for i in images
                ],
                "steps": steps,
                "seed": seed,
                "rights_confirmed": True,
            }
        )
    ).hexdigest()
    prior = await session.scalar(
        select(NarrativeStyleJob).where(
            NarrativeStyleJob.project_id == project_id,
            NarrativeStyleJob.idempotency_key == idempotency_key,
        )
    )
    if prior:
        if prior.request_hash != request_hash:
            raise DomainError(
                409,
                "Request changed",
                "Use a new request key for a different training run.",
                "style-replay-conflict",
            )
        return prior
    if project.archived_at:
        raise DomainError(
            409, "Project archived", "Restore the project before training.", "project-archived"
        )
    if conditioning not in {"text", "reference"} or (
        conditioning == "reference" and not character_look
    ):
        raise DomainError(
            422,
            "Invalid training conditioning",
            "Reference training requires a reviewed character look.",
            "invalid-training-conditioning",
        )
    if conditioning == "reference" and not reference_training_available:
        raise DomainError(
            503,
            "Reference training unavailable",
            "Reference-conditioned training is not enabled.",
            "reference-training-unavailable",
        )
    if not available or not model_manifest_sha256:
        raise DomainError(
            503,
            "Training unavailable",
            "Style training is not configured on this server.",
            "style-training-unavailable",
        )
    active = await session.scalar(
        select(NarrativeStyleJob.id)
        .where(NarrativeStyleJob.tenant_id == tenant_id, NarrativeStyleJob.status.in_(ACTIVE))
        .limit(1)
    )
    if active:
        raise DomainError(
            429,
            "Training already active",
            "Wait for or cancel the current training job.",
            "style-quota",
        )
    from flint_graph.application.services.narrative_character_adapters import training_look
    from flint_graph.application.services.narrative_looks import look_snapshot
    from flint_graph.infrastructure.db.narrative_character_adapter_models import (
        NarrativeCharacterAdapter,
    )

    look = (
        await training_look(
            session,
            tenant_id=tenant_id,
            project_id=project_id,
            target=character_look,
            images=images,
        )
        if character_look
        else None
    )
    frozen = []
    seen = set()
    for image in images:
        asset = await session.scalar(
            select(NarrativeAsset).where(
                NarrativeAsset.id == image["asset_id"],
                NarrativeAsset.project_id == project_id,
                NarrativeAsset.tenant_id == tenant_id,
            )
        )
        if asset is None:
            raise NotFoundError("Training image was not found.")
        if (
            asset.status != "approved"
            or asset.kind not in {"image", "sprite", "background", "character_portrait"}
            or asset.sha256 in seen
            or not asset.width
            or not asset.height
            or not 64 <= min(asset.width, asset.height)
            or max(asset.width, asset.height) > 2560
            or max(asset.width, asset.height) / min(asset.width, asset.height) > 4
        ):
            raise DomainError(
                422,
                "Invalid training image",
                "Choose 4-12 distinct approved images, 64-2560 pixels per edge and at most 4:1.",
                "invalid-style-image",
            )
        try:
            caption = clean_appearance(image["caption"])
            if not caption or len(caption) > 600:
                raise ValueError("A reviewed content caption is required.")
            policy.check(caption)
        except ValueError as error:
            raise DomainError(422, "Invalid caption", str(error), "invalid-style-caption") from None
        seen.add(asset.sha256)
        frozen.append(
            {
                "asset_id": str(asset.id),
                **(
                    {
                        "look_sha256": look.sha256,
                        "character_id": look.character_id,
                        "same_look_confirmed": True,
                        "anatomy_reviewed": True,
                    }
                    if look
                    else {}
                ),
                "sha256": asset.sha256,
                "size_bytes": asset.size_bytes,
                "name": asset.name,
                "caption": caption,
                "license": asset.license,
                "rights_confirmed": True,
                "policy_sha256": sha256(
                    canonical_json({"negative": policy.negative, "blocked": list(policy.blocked)})
                ).hexdigest(),
                "prompt_bundle_sha256": current_snapshot().sha256,
            }
        )
    await ensure_training_anatomy(
        session, tenant_id=tenant_id, project_id=project_id, hashes=list(seen)
    )
    job_id = uuid4()
    row = NarrativeStyleJob(
        id=job_id,
        tenant_id=tenant_id,
        project_id=project_id,
        author_user_id=author_user_id,
        name=name.strip(),
        images=frozen,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        model_manifest_sha256=model_manifest_sha256,
        dataset_sha256=sha256(canonical_json(frozen)).hexdigest(),
        recipe_sha256=REFERENCE_RECIPE_SHA if conditioning == "reference" else RECIPE_SHA,
        trigger="fgstyle_" + job_id.hex,
        steps=steps,
        seed=seed,
    )
    session.add(row)
    await charge_usage(
        session, user_id=author_user_id, kind="training", units=1, subject=f"style_job:{job_id}"
    )
    await session.flush()
    if look:
        session.add(
            NarrativeCharacterAdapter(
                job_id=row.id,
                project_id=project_id,
                tenant_id=tenant_id,
                character_id=look.character_id,
                look_id=look.id,
                snapshot=look_snapshot(look),
            )
        )
        await session.flush()
    await append_outbox_message(
        session,
        tenant_id=tenant_id,
        aggregate_type="narrative_style_job",
        aggregate_id=row.id,
        topic=QUEUED,
        payload={"schema_version": "1", "tenant_id": str(tenant_id), "job_id": str(row.id)},
    )
    return row


async def cancel_style(
    session: AsyncSession, *, tenant_id: UUID, project_id: UUID, job_id: UUID
) -> NarrativeStyleJob:
    row = await get_style(
        session, tenant_id=tenant_id, project_id=project_id, job_id=job_id, lock=True
    )
    if row.status in ACTIVE and not row.cancel_requested:
        row.cancel_requested = True
        # A never-started job can close immediately, even if no worker is present.
        if row.status == "queued":
            row.status, row.finished_at = "cancelled", datetime.now(UTC)
        await append_outbox_message(
            session,
            tenant_id=tenant_id,
            aggregate_type="narrative_style_job",
            aggregate_id=row.id,
            topic=CANCELLED,
            payload={"schema_version": "1", "tenant_id": str(tenant_id), "job_id": str(row.id)},
        )
    await session.flush()
    return row

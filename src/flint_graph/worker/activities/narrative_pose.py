"""Pose execution extends the image supervisor, with verified frozen references."""

from dataclasses import fields, replace
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from temporalio import activity
from temporalio.exceptions import ApplicationError

from flint_graph.application.narrative_image_workflow import (
    RUN_IMAGE_ACTIVITY,
    ImageJobOutcome,
    ImageJobPayload,
)
from flint_graph.application.services.narrative_images import ImageWork
from flint_graph.infrastructure.db.models import NarrativeAsset
from flint_graph.infrastructure.db.narrative_look_models import NarrativeLookJob
from flint_graph.infrastructure.db.narrative_pose_models import (
    NarrativePoseJob,
    NarrativePoseReference,
)
from flint_graph.infrastructure.db.narrative_style_models import (
    NarrativePoseStyle,
    NarrativeStyleJob,
)
from flint_graph.infrastructure.narrative_imagegen import (
    GenerationRequest,
    GenerationResult,
    ImageGenerationError,
    ImageGenerator,
)
from flint_graph.infrastructure.narrative_posegen import PoseGenerationRequest, PoseStyleAdapter
from flint_graph.narrative.poses import MODEL_REPO, MODEL_REVISION
from flint_graph.narrative.style_weights import MAX_ADAPTER_BYTES, validate_adapter
from flint_graph.narrative.values import canonical_json
from flint_graph.worker.activities.narrative_image import NarrativeImageActivities


class NarrativePoseActivities(NarrativeImageActivities):
    @activity.defn(name=RUN_IMAGE_ACTIVITY)
    async def run(self, payload: ImageJobPayload) -> ImageJobOutcome:
        data, _, _ = self._context(payload)
        async with self.factory() as session:
            plan = await session.get(NarrativePoseJob, UUID(data["job_id"]))
            if plan is None or str(plan.tenant_id) != data["tenant_id"]:
                raise ApplicationError("pose_identity", non_retryable=True)
        return await super().run(payload)

    async def _request(self, work: ImageWork) -> GenerationRequest:
        async with self.factory() as session:
            plan = await session.get(NarrativePoseJob, work.job_id)
            if plan is None:
                raise ImageGenerationError("pose_plan_missing")
            snapshot = await session.get(
                NarrativeLookJob,
                (work.job_id, plan.character_id),
            )
            if plan is None or snapshot is None or self.generator is None:
                raise ImageGenerationError("pose_plan_missing")
            generator = self.generator
            if (
                generator.model.repo != MODEL_REPO
                or generator.model.revision != MODEL_REVISION
                or getattr(generator, "model_manifest_sha256", None) != plan.model_manifest_sha256
                or (
                    work.request.cutout
                    and getattr(generator, "cutout_manifest_sha256", None)
                    != plan.cutout_manifest_sha256
                )
            ):
                raise ImageGenerationError("model_pin_mismatch")
            asset = await session.get(NarrativeAsset, UUID(snapshot.snapshot["asset_id"]))
            if (
                asset is None
                or asset.project_id != work.project_id
                or asset.tenant_id != work.tenant_id
                or asset.status != "approved"
                or asset.sha256 != snapshot.snapshot["source_sha256"]
            ):
                raise ImageGenerationError("reference_unavailable")
            references = list(
                await session.scalars(
                    select(NarrativePoseReference)
                    .where(NarrativePoseReference.job_id == plan.job_id)
                    .order_by(NarrativePoseReference.position)
                )
            )
            additional = []
            if references:
                if (
                    references[0].asset_id != asset.id
                    or references[0].sha256 != asset.sha256
                    or references[0].position != 0
                ):
                    raise ImageGenerationError("reference_unavailable")
                for item in references[1:]:
                    extra = await session.get(NarrativeAsset, item.asset_id)
                    if (
                        extra is None
                        or extra.status != "approved"
                        or extra.project_id != work.project_id
                        or extra.tenant_id != work.tenant_id
                        or extra.sha256 != item.sha256
                        or extra.size_bytes != item.size_bytes
                        or extra.character_id not in (None, plan.character_id)
                    ):
                        raise ImageGenerationError("reference_unavailable")
                    additional.append(
                        await self._image(work, extra.id, item.size_bytes, item.sha256)
                    )
            data = await self._image(work, asset.id, asset.size_bytes, asset.sha256)
            binding = await session.get(NarrativePoseStyle, work.job_id)
            style_adapter = None
            if binding:
                style = await session.get(NarrativeStyleJob, binding.style_id)
                if (
                    not style
                    or style.project_id != work.project_id
                    or style.tenant_id != work.tenant_id
                    or style.status != "completed"
                    or not style.weights_key
                    or not style.weights_size
                    or style.weights_sha256 != binding.weights_sha256
                    or style.model_manifest_sha256 != plan.model_manifest_sha256
                ):
                    raise ImageGenerationError("style_unavailable")
                weights = await self.store.get_verified(
                    style.weights_key,
                    expected_size=style.weights_size,
                    expected_sha256=binding.weights_sha256,
                    max_bytes=MAX_ADAPTER_BYTES,
                )
                validate_adapter(
                    weights,
                    base_hash=style.model_manifest_sha256,
                    dataset_hash=style.dataset_sha256,
                    recipe_hash=style.recipe_sha256,
                )
                style_adapter = PoseStyleAdapter(
                    weights, style.dataset_sha256, style.recipe_sha256, binding.strength
                )
        return PoseGenerationRequest(
            **{item.name: getattr(work.request, item.name) for item in fields(work.request)},
            reference=data,
            additional_references=tuple(additional),
            style_adapter=style_adapter,
        )

    async def _generate(
        self,
        generator: ImageGenerator,
        request: GenerationRequest,
        job_id: UUID,
        token: UUID,
    ) -> GenerationResult:
        result = await super()._generate(generator, request, job_id, token)
        async with self.factory() as session:
            plan = await session.get(NarrativePoseJob, job_id)
            assert plan is not None
            look = await session.get(NarrativeLookJob, (job_id, plan.character_id))
            assert look is not None
            references = list(
                await session.scalars(
                    select(NarrativePoseReference)
                    .where(NarrativePoseReference.job_id == job_id)
                    .order_by(NarrativePoseReference.position)
                )
            )
            manifest = [
                {
                    "asset_id": str(item.asset_id),
                    "sha256": item.sha256,
                    "view": item.view,
                    "size_bytes": item.size_bytes,
                }
                for item in references
            ]
            if not manifest:
                # Legacy jobs have a frozen look snapshot but no reference-table rows.
                source = await session.get(NarrativeAsset, UUID(look.snapshot["asset_id"]))
                assert source is not None
                manifest = [
                    {
                        "asset_id": look.snapshot["asset_id"],
                        "sha256": look.snapshot["source_sha256"],
                        "view": "primary",
                        "size_bytes": source.size_bytes,
                    }
                ]
            binding = await session.get(NarrativePoseStyle, job_id)
            style_meta = (
                {
                    "style_id": str(binding.style_id),
                    "style_weights_sha256": binding.weights_sha256,
                    "style_strength": str(binding.strength),
                }
                if binding
                else {}
            )
            return replace(
                result,
                runtime={
                    **result.runtime,
                    **style_meta,
                    "operation": "pose",
                    "references_sha256": sha256(canonical_json(manifest)).hexdigest(),
                    "reference_count": str(len(manifest) or 1),
                    "look_sha256": look.snapshot["sha256"],
                    "source_sha256": look.snapshot["source_sha256"],
                    "model_manifest_sha256": plan.model_manifest_sha256,
                },
            )

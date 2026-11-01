"""Pose execution extends the image supervisor, with verified frozen references."""

from dataclasses import fields, replace
from uuid import UUID

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
from flint_graph.infrastructure.db.narrative_pose_models import NarrativePoseJob
from flint_graph.infrastructure.narrative_imagegen import (
    GenerationRequest,
    GenerationResult,
    ImageGenerationError,
    ImageGenerator,
)
from flint_graph.infrastructure.narrative_posegen import PoseGenerationRequest
from flint_graph.narrative.poses import MODEL_REPO, MODEL_REVISION
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
            data = await self._image(work, asset.id, asset.size_bytes, asset.sha256)
        return PoseGenerationRequest(
            **{item.name: getattr(work.request, item.name) for item in fields(work.request)},
            reference=data,
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
            return replace(
                result,
                runtime={
                    **result.runtime,
                    "operation": "pose",
                    "look_sha256": look.snapshot["sha256"],
                    "source_sha256": look.snapshot["source_sha256"],
                    "model_manifest_sha256": plan.model_manifest_sha256,
                },
            )

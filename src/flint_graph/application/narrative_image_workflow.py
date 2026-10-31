"""Small deterministic contracts shared by the image relay, workflow and activities.

Payloads carry identifiers only: prompts, appearance text and image bytes stay in
PostgreSQL and object storage and never enter Temporal history (ADR 0039).
"""

from typing import Literal, TypedDict, cast
from uuid import UUID

IMAGE_WORKFLOW = "NarrativeImageJobWorkflow"
RUN_IMAGE_ACTIVITY = "run_narrative_image_job"
FINALIZE_IMAGE_ACTIVITY = "finalize_narrative_image_job"
RUN_ACTIVITY_ID = "run-image-job"
FINALIZE_ACTIVITY_ID = "finalize-image-job"
QUEUED_TOPIC = "narrative.image_job_queued"
CANCELLED_TOPIC = "narrative.image_job_cancelled"


class ImageJobPayload(TypedDict):
    schema_version: Literal["1"]
    tenant_id: str
    job_id: str


class FinalizeImagePayload(ImageJobPayload):
    cancelled: bool


class ImageJobOutcome(TypedDict):
    job_id: str
    status: Literal["completed", "failed", "cancelled", "stale"]


def validate_image_payload(value: object) -> ImageJobPayload:
    try:
        if (
            not isinstance(value, dict)
            or set(value) != {"schema_version", "tenant_id", "job_id"}
            or value["schema_version"] != "1"
        ):
            raise ValueError
        for name in ("tenant_id", "job_id"):
            raw = value[name]
            if not isinstance(raw, str) or len(raw) != 36 or str(UUID(raw)) != raw:
                raise ValueError
        return ImageJobPayload(
            schema_version="1", tenant_id=value["tenant_id"], job_id=value["job_id"]
        )
    except (ValueError, TypeError, KeyError):
        raise ValueError("Invalid narrative image payload") from None


def image_job_workflow_id(payload: ImageJobPayload) -> str:
    return "narrative-image-job-" + payload["job_id"]


# Voice jobs (ADR 0043) use the same IDs-only payload and fenced supervision.
VOICE_WORKFLOW = "NarrativeVoiceJobWorkflow"
RUN_VOICE_ACTIVITY = "run_narrative_voice_job"
FINALIZE_VOICE_ACTIVITY = "finalize_narrative_voice_job"
RUN_VOICE_ACTIVITY_ID = "run-voice-job"
FINALIZE_VOICE_ACTIVITY_ID = "finalize-voice-job"
VOICE_QUEUED_TOPIC = "narrative.voice_job_queued"
VOICE_CANCELLED_TOPIC = "narrative.voice_job_cancelled"


def voice_job_workflow_id(payload: ImageJobPayload) -> str:
    return "narrative-voice-job-" + payload["job_id"]


def validate_image_outcome(value: object, *, job_id: str) -> ImageJobOutcome:
    if (
        not isinstance(value, dict)
        or set(value) != {"job_id", "status"}
        or value["job_id"] != job_id
        or value["status"] not in ("completed", "failed", "cancelled", "stale")
    ):
        raise ValueError("Invalid narrative image outcome")
    return cast(ImageJobOutcome, {"job_id": job_id, "status": value["status"]})

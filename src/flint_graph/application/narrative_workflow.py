"""Small deterministic contracts shared by relay, workflow and activity edges."""

from typing import Literal, TypedDict
from uuid import UUID

NARRATIVE_RELEASE_WORKFLOW = "NarrativeReleaseWorkflow"
BUILD_NARRATIVE_RELEASE_ACTIVITY = "build_narrative_release"
FINALIZE_NARRATIVE_RELEASE_ACTIVITY = "finalize_narrative_release"
BUILD_ACTIVITY_ID = "build-release"
FINALIZE_ACTIVITY_ID = "finalize-release"
QUEUED_TOPIC = "narrative.release_queued"
CANCELLED_TOPIC = "narrative.release_cancelled"


class ReleasePayload(TypedDict):
    schema_version: Literal["1"]
    tenant_id: str
    release_id: str
    job_id: str


class ReleaseResult(TypedDict):
    job_id: str
    status: Literal["completed", "failed", "cancelled", "stale"]


class SupervisionPayload(ReleasePayload):
    cancelled: bool


def validate_release_payload(value: object) -> ReleasePayload:
    try:
        if (
            not isinstance(value, dict)
            or set(value) != {"schema_version", "tenant_id", "release_id", "job_id"}
            or value["schema_version"] != "1"
        ):
            raise ValueError
        for name in ("tenant_id", "release_id", "job_id"):
            raw = value[name]
            if not isinstance(raw, str) or len(raw) != 36 or str(UUID(raw)) != raw:
                raise ValueError
        return ReleasePayload(
            schema_version="1",
            tenant_id=value["tenant_id"],
            release_id=value["release_id"],
            job_id=value["job_id"],
        )
    except (ValueError, TypeError, KeyError):
        raise ValueError("Invalid narrative release payload") from None


def release_workflow_id(payload: ReleasePayload) -> str:
    return "narrative-release-" + payload["job_id"]

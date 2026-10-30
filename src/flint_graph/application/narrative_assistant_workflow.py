"""Small deterministic contracts shared by the assistant relay, workflow and activities.

Payloads carry identifiers only: requests, replies, story text and proposals stay
in PostgreSQL and never enter Temporal history.
"""

from typing import Literal, TypedDict, cast
from uuid import UUID

TURN_WORKFLOW = "NarrativeAssistantTurnWorkflow"
RUN_TURN_ACTIVITY = "run_narrative_assistant_turn"
FINALIZE_TURN_ACTIVITY = "finalize_narrative_assistant_turn"
RUN_ACTIVITY_ID = "run-turn"
FINALIZE_ACTIVITY_ID = "finalize-turn"
QUEUED_TOPIC = "narrative.assistant_turn_queued"
CANCELLED_TOPIC = "narrative.assistant_turn_cancelled"


class TurnPayload(TypedDict):
    schema_version: Literal["1"]
    tenant_id: str
    turn_id: str


class FinalizePayload(TurnPayload):
    cancelled: bool


class TurnOutcome(TypedDict):
    turn_id: str
    status: Literal["completed", "failed", "cancelled", "stale"]


def validate_turn_payload(value: object) -> TurnPayload:
    try:
        if (
            not isinstance(value, dict)
            or set(value) != {"schema_version", "tenant_id", "turn_id"}
            or value["schema_version"] != "1"
        ):
            raise ValueError
        for name in ("tenant_id", "turn_id"):
            raw = value[name]
            if not isinstance(raw, str) or len(raw) != 36 or str(UUID(raw)) != raw:
                raise ValueError
        return TurnPayload(
            schema_version="1", tenant_id=value["tenant_id"], turn_id=value["turn_id"]
        )
    except (ValueError, TypeError, KeyError):
        raise ValueError("Invalid narrative assistant payload") from None


def turn_workflow_id(payload: TurnPayload) -> str:
    return "narrative-assistant-turn-" + payload["turn_id"]


def validate_turn_outcome(value: object, *, turn_id: str) -> TurnOutcome:
    if (
        not isinstance(value, dict)
        or set(value) != {"turn_id", "status"}
        or value["turn_id"] != turn_id
        or value["status"] not in ("completed", "failed", "cancelled", "stale")
    ):
        raise ValueError("Invalid narrative assistant outcome")
    return cast(TurnOutcome, {"turn_id": turn_id, "status": value["status"]})

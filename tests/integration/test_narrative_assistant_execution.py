"""Assistant dispatch and fenced activities; default tests call no model or Temporal server."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from flint_graph.application.narrative_assistant_workflow import (
    CANCELLED_TOPIC,
    FINALIZE_TURN_ACTIVITY,
    QUEUED_TOPIC,
    RUN_TURN_ACTIVITY,
    TURN_WORKFLOW,
    TurnPayload,
    turn_workflow_id,
    validate_turn_outcome,
    validate_turn_payload,
)
from flint_graph.application.services.narrative_assistant import register_turn_workflow
from flint_graph.application.services.narrative_assistant_relay import (
    recover_stale_turns,
    relay_assistant_batch,
)
from flint_graph.config import Settings, get_settings
from flint_graph.domain.enums import OutboxMessageStatus
from flint_graph.infrastructure.db.models import (
    NarrativeAssistantProposal,
    NarrativeAssistantTurn,
    OutboxMessage,
)
from flint_graph.infrastructure.narrative_assistant import DeterministicNarrativeAssistant
from flint_graph.main import app
from flint_graph.narrative.assistant.turn import AssistantModelError, ModelReply
from flint_graph.worker.activities.narrative_assistant import NarrativeAssistantActivities

VALID = json.dumps(
    {
        "reply": "A storm arrives.",
        "proposal": {
            "summary": "Add a storm",
            "operations": [
                {
                    "op": "upsert_node",
                    "id": "storm",
                    "node": {"type": "line", "text": "Thunder.", "next": "ending"},
                },
                {
                    "op": "upsert_node",
                    "id": "opening",
                    "node": {"type": "line", "text": "Dawn.", "next": "storm"},
                },
            ],
        },
    }
)


def test_turn_payloads_and_outcomes_are_closed_id_only_contracts():
    turn, tenant = str(uuid4()), str(uuid4())
    payload = validate_turn_payload({"schema_version": "1", "tenant_id": tenant, "turn_id": turn})
    assert turn_workflow_id(payload) == "narrative-assistant-turn-" + turn
    for bad in [
        {"schema_version": "1", "tenant_id": tenant},
        {"schema_version": "2", "tenant_id": tenant, "turn_id": turn},
        {"schema_version": "1", "tenant_id": tenant, "turn_id": turn, "request": "PRIVATE"},
        {"schema_version": "1", "tenant_id": tenant, "turn_id": turn.upper()},
    ]:
        with pytest.raises(ValueError):
            validate_turn_payload(bad)
    assert validate_turn_outcome({"turn_id": turn, "status": "completed"}, turn_id=turn)
    with pytest.raises(ValueError):
        validate_turn_outcome({"turn_id": turn, "status": "done"}, turn_id=turn)


class Dispatcher:
    def __init__(self, closed=False):
        self.started, self.cancelled, self.run_id, self.is_closed = [], [], uuid4(), closed

    async def start(self, payload):
        self.started.append(payload)
        return self.run_id

    async def cancel(self, payload, *, run_id):
        self.cancelled.append((payload, run_id))

    async def closed(self, payload, *, run_id):
        return self.is_closed


@pytest.fixture
async def turn_case(narrative_env):
    client, factory, _ = narrative_env
    app.dependency_overrides[get_settings] = lambda: Settings(env="test")
    try:
        workspace = (await client.post("/v1/workspaces", json={"name": "Assistant jobs"})).json()
        headers = {"X-Tenant-ID": workspace["id"]}
        project = (
            await client.post(
                "/v1/narrative/projects",
                headers=headers,
                json={"name": "PRIVATE CANARY", "idempotency_key": str(uuid4())},
            )
        ).json()
        path = f"/v1/narrative/projects/{project['id']}/assistant"
        thread = (
            await client.post(
                f"{path}/threads",
                headers=headers,
                json={"title": "Jobs", "idempotency_key": str(uuid4())},
            )
        ).json()

        async def ask(request="Add a storm."):
            response = await client.post(
                f"{path}/threads/{thread['id']}/turns",
                headers=headers,
                json={
                    "request": request,
                    "base_revision_id": project["head_revision_id"],
                    "idempotency_key": str(uuid4()),
                },
            )
            assert response.status_code == 202
            turn = response.json()
            return TurnPayload(schema_version="1", tenant_id=workspace["id"], turn_id=turn["id"])

        async def cancel(payload):
            return (
                await client.post(
                    f"{path}/threads/{thread['id']}/turns/{payload['turn_id']}/cancel",
                    headers=headers,
                )
            ).json()

        yield factory, ask, cancel
    finally:
        app.dependency_overrides.pop(get_settings, None)


async def turn_row(factory, payload):
    async with factory() as session:
        return await session.scalar(
            select(NarrativeAssistantTurn).where(
                NarrativeAssistantTurn.id == UUID(payload["turn_id"])
            )
        )


async def outbox(factory, topic):
    async with factory() as session:
        return list(
            await session.scalars(select(OutboxMessage).where(OutboxMessage.topic == topic))
        )


@pytest.mark.anyio
async def test_relay_starts_registers_and_publishes_only_assistant_topics(turn_case):
    factory, ask, cancel = turn_case
    payload = await ask()
    async with factory() as session:
        session.add(
            OutboxMessage(
                tenant_id=UUID(payload["tenant_id"]),
                topic="narrative.release_queued",
                aggregate_type="narrative_release_job",
                aggregate_id=uuid4(),
                payload={},
            )
        )
        await session.commit()
    dispatcher = Dispatcher()
    assert await relay_assistant_batch(factory, dispatcher=dispatcher) == 1
    assert dispatcher.started == [payload]
    turn = await turn_row(factory, payload)
    assert (turn.status, turn.workflow_run_id, turn.activity_attempt) == (
        "queued",
        dispatcher.run_id,
        0,
    )
    [queued] = await outbox(factory, QUEUED_TOPIC)
    assert queued.status == OutboxMessageStatus.PUBLISHED
    [release] = await outbox(factory, "narrative.release_queued")
    assert release.status == OutboxMessageStatus.PENDING, "Never consumes other topics"
    assert await relay_assistant_batch(factory, dispatcher=dispatcher) == 0

    async with factory() as session:
        await session.execute(
            update(NarrativeAssistantTurn)
            .where(NarrativeAssistantTurn.id == UUID(payload["turn_id"]))
            .values(status="running", execution_token=uuid4(), activity_attempt=1)
        )
        await session.commit()
    assert (await cancel(payload))["cancel_requested"] is True
    assert await relay_assistant_batch(factory, dispatcher=dispatcher) == 1
    assert dispatcher.cancelled == [(payload, dispatcher.run_id)]
    [cancelled] = await outbox(factory, CANCELLED_TOPIC)
    assert cancelled.status == OutboxMessageStatus.PUBLISHED


@pytest.mark.anyio
async def test_cancelled_before_dispatch_never_starts_and_bad_messages_back_off(turn_case):
    factory, ask, cancel = turn_case
    payload = await ask()
    assert (await cancel(payload))["status"] == "cancelled"
    dispatcher = Dispatcher()
    assert await relay_assistant_batch(factory, dispatcher=dispatcher) == 1
    assert dispatcher.started == []
    async with factory() as session:
        session.add(
            OutboxMessage(
                tenant_id=UUID(payload["tenant_id"]),
                topic=QUEUED_TOPIC,
                aggregate_type="narrative_assistant_turn",
                aggregate_id=uuid4(),
                payload={**payload, "turn_id": str(uuid4())},
            )
        )
        await session.commit()
    assert await relay_assistant_batch(factory, dispatcher=dispatcher) == 0
    failed = [m for m in await outbox(factory, QUEUED_TOPIC) if m.status != "published"]
    assert [(m.attempt_count, m.last_error) for m in failed] == [(1, "dispatch_unavailable")]
    assert failed[0].available_at.replace(tzinfo=UTC) > datetime.now(UTC)


class Failing:
    provider = "scripted"

    def __init__(self, code):
        self.code = code

    async def respond(self, messages, schema):
        raise AssistantModelError(self.code)


def environment(payload, run_id, attempt=1, activity_type=RUN_TURN_ACTIVITY):
    env = ActivityEnvironment()
    env.info = replace(
        env.info,
        activity_type=activity_type,
        workflow_id=turn_workflow_id(payload),
        workflow_type=TURN_WORKFLOW,
        workflow_run_id=str(run_id),
        attempt=attempt,
    )
    return env


async def registered(factory, payload, run_id=None):
    run_id = run_id or uuid4()
    async with factory() as session:
        await register_turn_workflow(
            session,
            tenant_id=UUID(payload["tenant_id"]),
            turn_id=UUID(payload["turn_id"]),
            workflow_run_id=run_id,
        )
        await session.commit()
    return run_id


def activities(factory, model):
    return NarrativeAssistantActivities(factory=factory, model=model, context_chars=24000)


@pytest.mark.anyio
async def test_activity_runs_the_registered_turn_and_persists_a_reviewable_proposal(turn_case):
    factory, ask, _ = turn_case
    payload = await ask()
    run_id = await registered(factory, payload)
    work = activities(factory, DeterministicNarrativeAssistant([VALID]))
    outcome = await environment(payload, run_id).run(work.run, payload)
    assert outcome == {"turn_id": payload["turn_id"], "status": "completed"}
    turn = await turn_row(factory, payload)
    assert (turn.status, turn.reply, turn.provider) == (
        "completed",
        "A storm arrives.",
        "deterministic",
    )
    assert turn.execution_token is None and turn.prompt_sha256
    async with factory() as session:
        proposal = await session.scalar(select(NarrativeAssistantProposal))
    assert proposal.status == "ready" and proposal.touched == ["nodes.opening", "nodes.storm"]
    replay = await environment(payload, run_id, attempt=2).run(work.run, payload)
    assert replay["status"] == "stale", "A finished turn is never re-run"


@pytest.mark.anyio
async def test_unregistered_runs_retry_and_foreign_runs_cannot_claim(turn_case):
    factory, ask, _ = turn_case
    payload = await ask()
    work = activities(factory, DeterministicNarrativeAssistant([VALID]))
    # Started but not yet registered: retry rather than closing the workflow as stale.
    with pytest.raises(ApplicationError) as raised:
        await environment(payload, uuid4()).run(work.run, payload)
    assert raised.value.type == "registration_pending" and not raised.value.non_retryable
    await registered(factory, payload)
    assert (await environment(payload, uuid4()).run(work.run, payload))["status"] == "stale"
    assert (await turn_row(factory, payload)).status == "queued"


@pytest.mark.anyio
async def test_transient_provider_errors_retry_then_fail_with_a_safe_code(turn_case):
    factory, ask, _ = turn_case
    payload = await ask()
    run_id = await registered(factory, payload)
    work = activities(factory, Failing("provider_timeout"))
    with pytest.raises(ApplicationError) as raised:
        await environment(payload, run_id, attempt=1).run(work.run, payload)
    assert raised.value.type == "provider_timeout" and not raised.value.non_retryable
    assert (await turn_row(factory, payload)).status == "running"
    outcome = await environment(payload, run_id, attempt=3).run(work.run, payload)
    assert outcome["status"] == "failed"
    turn = await turn_row(factory, payload)
    assert (turn.status, turn.error_code, turn.execution_token) == (
        "failed",
        "provider_timeout",
        None,
    )


@pytest.mark.anyio
async def test_disabled_provider_fails_the_turn_without_retrying(turn_case):
    factory, ask, _ = turn_case
    payload = await ask()
    run_id = await registered(factory, payload)
    outcome = await environment(payload, run_id).run(activities(factory, None).run, payload)
    assert outcome["status"] == "failed"
    assert (await turn_row(factory, payload)).error_code == "assistant_unavailable"


@pytest.mark.anyio
async def test_finalizer_closes_an_abandoned_turn_of_its_own_run_only(turn_case):
    factory, ask, cancel = turn_case
    payload = await ask()
    run_id = await registered(factory, payload)
    work = activities(factory, Failing("provider_unavailable"))
    with pytest.raises(ApplicationError):
        await environment(payload, run_id).run(work.run, payload)
    final = {**payload, "cancelled": False}
    stale = await environment(payload, uuid4(), activity_type=FINALIZE_TURN_ACTIVITY).run(
        work.finalize, final
    )
    assert stale["status"] == "stale" and (await turn_row(factory, payload)).status == "running"
    done = await environment(payload, run_id, activity_type=FINALIZE_TURN_ACTIVITY).run(
        work.finalize, final
    )
    assert done["status"] == "failed"
    assert (await turn_row(factory, payload)).error_code == "worker_interrupted"

    second = await ask("Again.")
    run_id = await registered(factory, second)
    with pytest.raises(ApplicationError):
        await environment(second, run_id).run(work.run, second)
    assert (await cancel(second))["cancel_requested"] is True
    cancelled = await environment(second, run_id, activity_type=FINALIZE_TURN_ACTIVITY).run(
        work.finalize, {**second, "cancelled": True}
    )
    assert cancelled["status"] == "cancelled"


@pytest.mark.anyio
async def test_recovery_fails_stale_turns_only_when_their_run_is_closed(turn_case):
    factory, ask, _ = turn_case
    payload = await ask()
    run_id = await registered(factory, payload)
    old = datetime.now(UTC) - timedelta(hours=2)
    async with factory() as session:
        await session.execute(
            update(NarrativeAssistantTurn)
            .where(NarrativeAssistantTurn.id == UUID(payload["turn_id"]))
            .values(status="running", execution_token=uuid4(), activity_attempt=1, started_at=old)
        )
        await session.commit()
    assert await recover_stale_turns(factory, dispatcher=Dispatcher(closed=False)) == 0
    assert (await turn_row(factory, payload)).status == "running"
    assert await recover_stale_turns(factory, dispatcher=Dispatcher(closed=True)) == 1
    turn = await turn_row(factory, payload)
    assert (turn.status, turn.error_code, turn.workflow_run_id) == (
        "failed",
        "worker_interrupted",
        run_id,
    )


@pytest.mark.anyio
async def test_reply_and_proposal_never_reach_activity_results_or_outbox(turn_case):
    factory, ask, _ = turn_case
    payload = await ask("PRIVATE REQUEST TEXT")
    run_id = await registered(factory, payload)

    class Echo:
        provider = "scripted"

        async def respond(self, messages, schema):
            return ModelReply(VALID, "echo", 1, 1)

    outcome = await environment(payload, run_id).run(activities(factory, Echo()).run, payload)
    assert set(outcome) == {"turn_id", "status"}
    for message in await outbox(factory, QUEUED_TOPIC):
        assert "PRIVATE" not in json.dumps(message.payload)

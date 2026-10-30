"""Separate narrative outbox delivery and accepted-run registration seam."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text

from flint_graph.application.narrative_workflow import ReleasePayload
from flint_graph.application.services.narrative_release_relay import (
    relay_narrative_batch,
    relay_narrative_message,
)
from flint_graph.config import Settings, get_settings
from flint_graph.domain.enums import OutboxMessageStatus
from flint_graph.infrastructure.db.models import NarrativeReleaseJob, OutboxMessage
from flint_graph.main import app


class RecordingDispatcher:
    def __init__(self):
        self.run_id = uuid4()
        self.calls = []
        self.fail = False

    async def start(self, payload: ReleasePayload) -> UUID:
        self.calls.append(("start", payload))
        if self.fail:
            raise RuntimeError("PRIVATE PROVIDER ERROR AND SOURCE")
        return self.run_id

    async def cancel(self, payload: ReleasePayload, *, run_id: UUID) -> None:
        self.calls.append(("cancel", payload, run_id))


@pytest.fixture
async def relay_case(narrative_env):
    client, factory, _backend = narrative_env
    app.dependency_overrides[get_settings] = lambda: Settings(
        env="test",
        narrative_releases_enabled=True,
        narrative_release_builder_image_digest="sha256:" + "a" * 64,
        narrative_release_toolchain_sha256="b" * 64,
    )
    try:
        workspace = (await client.post("/v1/workspaces", json={"name": "Relay"})).json()
        headers = {"X-Tenant-ID": workspace["id"]}
        project = (
            await client.post(
                "/v1/narrative/projects",
                headers=headers,
                json={"name": "Original", "idempotency_key": str(uuid4())},
            )
        ).json()
        path = f"/v1/narrative/projects/{project['id']}/releases"
        release = (
            await client.post(
                path,
                headers=headers,
                json={"revision_id": project["head_revision_id"], "idempotency_key": str(uuid4())},
            )
        ).json()
        yield client, factory, headers, f"{path}/{release['id']}", UUID(release["job"]["id"])
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.anyio
async def test_accepted_run_and_dispatch_ack_commit_together_and_replay(relay_case):
    _, factory, _, _, job_id = relay_case
    dispatcher = RecordingDispatcher()
    async with factory() as session:
        if session.bind.dialect.name == "sqlite":
            # sqlite3 legacy SELECT does not start a physical outer transaction.
            await session.execute(text("BEGIN"))
        assert await relay_narrative_message(session, dispatcher=dispatcher) == 1
        await session.rollback()  # Temporal accepted; database acknowledgement was lost.
    async with factory() as session:
        job = await session.get(NarrativeReleaseJob, job_id)
        assert job.workflow_run_id is None
        assert await relay_narrative_message(session, dispatcher=dispatcher) == 1
        await session.commit()
    async with factory() as session:
        job = await session.get(NarrativeReleaseJob, job_id)
        message = await session.scalar(
            select(OutboxMessage).where(OutboxMessage.aggregate_id == job_id)
        )
        assert job.workflow_run_id == dispatcher.run_id and job.activity_attempt == 0
        assert message.status == OutboxMessageStatus.PUBLISHED
        assert not await relay_narrative_message(session, dispatcher=dispatcher)
    assert len(dispatcher.calls) == 2
    assert set(dispatcher.calls[0][1]) == {"schema_version", "tenant_id", "release_id", "job_id"}


@pytest.mark.anyio
async def test_failed_dispatch_stays_retryable_without_raw_error_or_false_owner(relay_case):
    _, factory, _, _, job_id = relay_case
    dispatcher = RecordingDispatcher()
    dispatcher.fail = True
    async with factory() as session:
        assert not await relay_narrative_message(session, dispatcher=dispatcher)
        await session.commit()
    async with factory() as session:
        job = await session.get(NarrativeReleaseJob, job_id)
        message = await session.scalar(
            select(OutboxMessage).where(OutboxMessage.aggregate_id == job_id)
        )
        assert job.workflow_run_id is None
        assert message.status == OutboxMessageStatus.PENDING
        assert message.attempt_count == 1 and message.last_error == "dispatch_unavailable"
        assert message.available_at.replace(tzinfo=UTC) > datetime.now(UTC)
        assert not await relay_narrative_message(session, dispatcher=dispatcher)


@pytest.mark.anyio
async def test_start_precedes_cancel_and_cancellation_is_pinned_to_registered_run(relay_case):
    client, factory, headers, item, job_id = relay_case
    # Claim manually only to keep cancellation pending instead of immediate queued cancel.
    from flint_graph.application.services.narrative_release_execution import (
        claim_release_execution,
    )

    async with factory() as session:
        job = await session.get(NarrativeReleaseJob, job_id)
        scope = dict(tenant_id=job.tenant_id, release_id=job.release_id, job_id=job.id)
        # Register via relay first; the activity would then claim with SDK identity.
        dispatcher = RecordingDispatcher()
        assert await relay_narrative_message(session, dispatcher=dispatcher) == 1
        await claim_release_execution(
            session, **scope, token=uuid4(), workflow_run_id=dispatcher.run_id, activity_attempt=1
        )
        await session.commit()
    assert (await client.post(f"{item}/jobs/{job_id}/cancel", headers=headers)).status_code == 200
    async with factory() as session:
        # Replay the start with an older cancel timestamp: start priority is absolute.
        messages = list(
            await session.scalars(select(OutboxMessage).where(OutboxMessage.aggregate_id == job_id))
        )
        for message in messages:
            message.status = OutboxMessageStatus.PENDING
            message.available_at = datetime.now(UTC) - timedelta(
                minutes=1 if "queued" in message.topic else 2
            )
        await session.commit()
    dispatcher.calls.clear()
    assert await relay_narrative_batch(factory, dispatcher=dispatcher) == 2
    assert [call[0] for call in dispatcher.calls] == ["start", "cancel"]
    assert dispatcher.calls[-1][2] == dispatcher.run_id


@pytest.mark.anyio
async def test_first_registration_is_visible_while_second_dispatch_is_blocked(relay_case):
    client, factory, headers, _, job_id = relay_case
    project = (
        await client.post(
            "/v1/narrative/projects",
            headers=headers,
            json={"name": "Second", "idempotency_key": str(uuid4())},
        )
    ).json()
    second = await client.post(
        f"/v1/narrative/projects/{project['id']}/releases",
        headers=headers,
        json={"revision_id": project["head_revision_id"], "idempotency_key": str(uuid4())},
    )
    assert second.status_code == 202
    entered, proceed = asyncio.Event(), asyncio.Event()

    class SlowSecondDispatcher(RecordingDispatcher):
        async def start(self, payload):
            if self.calls:
                entered.set()
                await proceed.wait()
            return await super().start(payload)

    dispatcher = SlowSecondDispatcher()
    task = asyncio.create_task(relay_narrative_batch(factory, dispatcher=dispatcher))
    try:
        await asyncio.wait_for(entered.wait(), 10)
        async with factory() as session:
            first = await session.get(NarrativeReleaseJob, job_id)
            message = await session.scalar(
                select(OutboxMessage).where(OutboxMessage.aggregate_id == job_id)
            )
            assert first.workflow_run_id == dispatcher.run_id and first.activity_attempt == 0
            assert message.status == OutboxMessageStatus.PUBLISHED
    finally:
        proceed.set()
        result = await asyncio.wait_for(task, 10)
    assert result == 2


@pytest.mark.anyio
async def test_poison_payload_is_deferred_and_unrelated_topic_is_not_consumed(relay_case):
    _, factory, _, _, job_id = relay_case
    dispatcher = RecordingDispatcher()
    async with factory() as session:
        original = await session.scalar(
            select(OutboxMessage).where(OutboxMessage.aggregate_id == job_id)
        )
        original.payload = {**original.payload, "private_source": "PRIVATE SOURCE"}
        unrelated = OutboxMessage(
            tenant_id=original.tenant_id,
            topic="ingestion.job_queued",
            aggregate_type="ingestion_job",
            aggregate_id=uuid4(),
            payload={},
        )
        session.add(unrelated)
        await session.flush()
        unrelated_id = unrelated.id
        await session.commit()
    assert await relay_narrative_batch(factory, dispatcher=dispatcher) == 0
    assert not dispatcher.calls
    async with factory() as session:
        other = await session.get(OutboxMessage, unrelated_id)
        assert other.status == OutboxMessageStatus.PENDING and other.attempt_count == 0
        job = await session.get(NarrativeReleaseJob, job_id)
        assert job.workflow_run_id is None

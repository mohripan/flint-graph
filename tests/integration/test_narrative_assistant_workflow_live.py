"""Connected assistant turns on an owned Temporal: relay, workflow, activity, database.

Opt-in only. The optional Ollama case uses an explicitly named local model; nothing
here calls a paid provider or the workspace default database.
"""

import asyncio
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from temporalio.client import Client
from temporalio.worker import Worker

from flint_graph.application.narrative_assistant_workflow import TurnPayload, turn_workflow_id
from flint_graph.application.services.narrative_assistant_relay import relay_assistant_batch
from flint_graph.config import Settings, get_settings
from flint_graph.infrastructure.narrative_assistant import (
    DeterministicNarrativeAssistant,
    OllamaNarrativeAssistant,
)
from flint_graph.infrastructure.narrative_assistant_temporal import TemporalAssistantDispatcher
from flint_graph.main import app
from flint_graph.narrative.assistant.turn import ModelReply
from flint_graph.worker.activities.narrative_assistant import NarrativeAssistantActivities
from flint_graph.workflows.narrative_assistant import NarrativeAssistantTurnWorkflow

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.getenv("FLINT_GRAPH_NARRATIVE_TEMPORAL_FIXTURE"),
        reason="requires an explicit owned Temporal fixture metadata file",
    ),
]

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


class Blocking:
    provider = "scripted"

    def __init__(self):
        self.started = asyncio.Event()

    async def respond(self, messages, schema, on_delta=None):
        self.started.set()
        await asyncio.sleep(120)
        return ModelReply(VALID, "blocking", 0, 0)


@pytest.fixture
async def live_case(narrative_env):
    client, factory, _ = narrative_env
    app.dependency_overrides[get_settings] = lambda: Settings(env="test")
    owned = json.loads(
        await asyncio.to_thread(
            Path(os.environ["FLINT_GRAPH_NARRATIVE_TEMPORAL_FIXTURE"]).read_text
        )
    )
    assert owned["address"].startswith("127.0.0.1:")
    temporal = await Client.connect(owned["address"], namespace=owned["namespace"])
    queue = "assistant-live-" + uuid4().hex
    try:
        workspace = (await client.post("/v1/workspaces", json={"name": "Live chat"})).json()
        headers = {"X-Tenant-ID": workspace["id"]}
        project = (
            await client.post(
                "/v1/narrative/projects",
                headers=headers,
                json={"name": "Live chat", "idempotency_key": str(uuid4())},
            )
        ).json()
        base = f"/v1/narrative/projects/{project['id']}/assistant"
        thread = (
            await client.post(
                f"{base}/threads",
                headers=headers,
                json={"title": "Live", "idempotency_key": str(uuid4())},
            )
        ).json()
        turns = f"{base}/threads/{thread['id']}/turns"

        async def ask(request):
            response = await client.post(
                turns,
                headers=headers,
                json={
                    "request": request,
                    "base_revision_id": project["head_revision_id"],
                    "focus_node": "opening",
                    "idempotency_key": str(uuid4()),
                },
            )
            assert response.status_code == 202
            return response.json()

        async def state(turn_id):
            rows = (await client.get(turns, headers=headers)).json()
            return next(row for row in rows if row["id"] == turn_id)

        async def until(turn_id, statuses, seconds):
            async with asyncio.timeout(seconds):
                while (row := await state(turn_id))["status"] not in statuses:
                    await relay_assistant_batch(factory, dispatcher=dispatcher)
                    await asyncio.sleep(0.2)
            return row

        dispatcher = TemporalAssistantDispatcher(temporal, task_queue=queue)
        yield {
            "client": client,
            "headers": headers,
            "factory": factory,
            "temporal": temporal,
            "queue": queue,
            "dispatcher": dispatcher,
            "tenant": workspace["id"],
            "turns": turns,
            "ask": ask,
            "until": until,
        }
    finally:
        app.dependency_overrides.pop(get_settings, None)


def worker(case, model):
    activities = NarrativeAssistantActivities(
        factory=case["factory"], model=model, context_chars=24000
    )
    return Worker(
        case["temporal"],
        task_queue=case["queue"],
        workflows=[NarrativeAssistantTurnWorkflow],
        activities=[activities.run, activities.finalize],
        max_concurrent_activities=1,
        max_heartbeat_throttle_interval=timedelta(seconds=0.2),
    )


async def events(case, turn_id):
    url = f"{case['turns']}/{turn_id}/events"
    return (await case["client"].get(url, headers=case["headers"])).json()


async def test_connected_turn_completes_with_ids_only_history(live_case):
    case = live_case
    turn = await case["ask"]("PRIVATE LIVE REQUEST: add a storm.")
    model = DeterministicNarrativeAssistant([("PRIVATE THINKING about storms.", VALID)])
    async with worker(case, model):
        done = await case["until"](turn["id"], {"completed", "failed"}, 30)
    assert done["status"] == "completed" and done["reply"] == "A storm arrives."
    assert done["proposal"]["status"] == "ready"
    payload = TurnPayload(schema_version="1", tenant_id=case["tenant"], turn_id=turn["id"])
    handle = case["temporal"].get_workflow_handle(turn_workflow_id(payload))
    assert await handle.result() == {"turn_id": turn["id"], "status": "completed"}
    # Live progress is in PostgreSQL; workflow history stays IDs and status only.
    rows = await events(case, turn["id"])
    assert "".join(r["payload"]["text"] for r in rows if r["kind"] == "thinking") == (
        "PRIVATE THINKING about storms."
    )
    assert "".join(r["payload"]["text"] for r in rows if r["kind"] == "text") == done["reply"]
    assert rows[-1]["payload"] == {"status": "completed", "error_code": None}
    history = (await handle.fetch_history()).to_json()
    for private in ("PRIVATE LIVE REQUEST", "Thunder", "PRIVATE THINKING", "A storm arrives"):
        assert private not in history


async def test_cancelling_a_running_turn_stops_the_model_call(live_case):
    case = live_case
    turn = await case["ask"]("Write slowly.")
    model = Blocking()
    async with worker(case, model):
        await case["until"](turn["id"], {"running"}, 30)
        await asyncio.wait_for(model.started.wait(), 10)
        cancel = await case["client"].post(
            f"{case['turns']}/{turn['id']}/cancel", headers=case["headers"]
        )
        assert cancel.json()["cancel_requested"] is True
        done = await case["until"](turn["id"], {"cancelled", "failed", "completed"}, 40)
    assert done["status"] == "cancelled" and done["proposal"] is None
    final = (await events(case, turn["id"]))[-1]
    assert final["kind"] == "status" and final["payload"]["status"] == "cancelled"


@pytest.mark.skipif(
    not os.getenv("FLINT_GRAPH_NARRATIVE_ASSISTANT_OLLAMA_MODEL"),
    reason="requires an explicitly named locally installed Ollama model",
)
async def test_local_ollama_turn_produces_a_validated_proposal(live_case):
    case = live_case
    turn = await case["ask"](
        "Add a scene after the opening where a storm rolls in, then continue to the ending."
    )
    model = OllamaNarrativeAssistant(
        model=os.environ["FLINT_GRAPH_NARRATIVE_ASSISTANT_OLLAMA_MODEL"],
        context_tokens=16384,
        max_output_tokens=4096,
        temperature=0.6,
        timeout_seconds=300,
        base_url="http://127.0.0.1:11434",
        thinking=os.getenv("FLINT_GRAPH_NARRATIVE_ASSISTANT_THINKING", "true") != "false",
    )
    async with worker(case, model):
        done = await case["until"](turn["id"], {"completed", "failed"}, 600)
    assert done["status"] == "completed" and done["reply"]
    assert done["proposal"] is not None and done["proposal"]["status"] in ("ready", "invalid")
    rows = await events(case, turn["id"])
    kinds = {kind: sum(r["kind"] == kind for r in rows) for kind in ("step", "thinking", "text")}
    assert kinds["step"] and kinds["text"] and rows[-1]["kind"] == "status"
    print(
        json.dumps(
            {
                "proposal": done["proposal"],
                "model": done["model"],
                "attempts": done["attempts"],
                "events": kinds,
                "seconds": (
                    datetime.fromisoformat(done["finished_at"])
                    - datetime.fromisoformat(done["created_at"])
                ).total_seconds(),
            }
        )
    )
    assert UUID(done["proposal"]["id"])

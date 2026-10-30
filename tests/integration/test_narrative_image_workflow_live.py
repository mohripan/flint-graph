"""Connected image jobs on an owned Temporal: relay, workflow, activity, database (ADR 0039).

Opt-in only. The real-GPU case additionally needs the isolated runtime, the local
model and its pinned manifest; nothing here downloads a model or calls a paid service.
"""

import asyncio
import hashlib
import json
import os
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from temporalio.client import Client
from temporalio.worker import Worker
from test_narrative_characters_api import FakeGenerator, MemoryStore, use_settings

from flint_graph.api.dependencies import get_narrative_artifact_store
from flint_graph.application.narrative_image_workflow import ImageJobPayload, image_job_workflow_id
from flint_graph.application.services.narrative_image_relay import relay_image_batch
from flint_graph.config import get_settings
from flint_graph.infrastructure.narrative_image_temporal import TemporalImageDispatcher
from flint_graph.infrastructure.narrative_imagegen import (
    LocalImageGenerator,
    OllamaGpuReleaser,
    runtime_paths,
    verify_model,
)
from flint_graph.main import app
from flint_graph.worker.activities.narrative_image import NarrativeImageActivities
from flint_graph.workflows.narrative_image import NarrativeImageJobWorkflow

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.getenv("FLINT_GRAPH_NARRATIVE_TEMPORAL_FIXTURE"),
        reason="requires an explicit owned Temporal fixture metadata file",
    ),
]


class Blocking(FakeGenerator):
    def __init__(self):
        super().__init__()
        self.started, self.stopped = asyncio.Event(), asyncio.Event()

    async def generate(self, request, *, on_progress):
        self.started.set()
        try:
            await asyncio.sleep(120)
        finally:
            self.stopped.set()
        return await super().generate(request, on_progress=on_progress)


@pytest.fixture
async def live_case(narrative_env):
    client, factory, _ = narrative_env
    original = use_settings()
    store = MemoryStore()
    app.dependency_overrides[get_narrative_artifact_store] = lambda: store
    owned = json.loads(
        await asyncio.to_thread(
            Path(os.environ["FLINT_GRAPH_NARRATIVE_TEMPORAL_FIXTURE"]).read_text
        )
    )
    assert owned["address"].startswith("127.0.0.1:")
    temporal = await Client.connect(owned["address"], namespace=owned["namespace"])
    queue = "image-live-" + uuid4().hex
    try:
        workspace = (await client.post("/v1/workspaces", json={"name": "Live images"})).json()
        headers = {"X-Tenant-ID": workspace["id"]}
        project = (
            await client.post(
                "/v1/narrative/projects",
                headers=headers,
                json={"name": "Live images", "idempotency_key": str(uuid4())},
            )
        ).json()
        base = f"/v1/narrative/projects/{project['id']}"
        dispatcher = TemporalImageDispatcher(temporal, task_queue=queue)

        async def generate(appearance, count=2):
            response = await client.post(
                f"{base}/characters/mira/portrait-jobs",
                headers=headers,
                json={
                    "appearance": appearance,
                    "character_type": "girl",
                    "framing": "portrait",
                    "count": count,
                    "idempotency_key": str(uuid4()),
                },
            )
            assert response.status_code == 202, response.text
            return response.json()

        async def until(job_id, statuses, seconds):
            async with asyncio.timeout(seconds):
                while True:
                    row = (await client.get(f"{base}/image-jobs/{job_id}", headers=headers)).json()
                    if row["status"] in statuses:
                        return row
                    await relay_image_batch(factory, dispatcher=dispatcher)
                    await asyncio.sleep(0.2)

        yield {
            "client": client,
            "headers": headers,
            "base": base,
            "factory": factory,
            "store": store,
            "temporal": temporal,
            "queue": queue,
            "tenant": workspace["id"],
            "generate": generate,
            "until": until,
        }
    finally:
        app.dependency_overrides[get_settings] = original
        app.dependency_overrides.pop(get_narrative_artifact_store, None)


def worker(case, generator, releaser=None):
    activities = NarrativeImageActivities(
        factory=case["factory"], generator=generator, store=case["store"], releaser=releaser
    )
    return Worker(
        case["temporal"],
        task_queue=case["queue"],
        workflows=[NarrativeImageJobWorkflow],
        activities=[activities.run, activities.finalize],
        max_concurrent_activities=1,
        max_heartbeat_throttle_interval=timedelta(seconds=0.2),
    )


async def test_connected_job_completes_with_ids_only_history(live_case):
    case = live_case
    job = await case["generate"]("PRIVATE APPEARANCE silver hair")
    async with worker(case, FakeGenerator()):
        done = await case["until"](job["id"], {"completed", "failed"}, 30)
    assert done["status"] == "completed" and len(done["assets"]) == 2
    payload = ImageJobPayload(schema_version="1", tenant_id=case["tenant"], job_id=job["id"])
    handle = case["temporal"].get_workflow_handle(image_job_workflow_id(payload))
    assert await handle.result() == {"job_id": job["id"], "status": "completed"}
    history = (await handle.fetch_history()).to_json()
    assert "PRIVATE APPEARANCE" not in history and "masterpiece" not in history


async def test_cancelling_a_running_job_stops_generation(live_case):
    case = live_case
    job = await case["generate"]("slow")
    generator = Blocking()
    async with worker(case, generator):
        await case["until"](job["id"], {"running"}, 30)
        await asyncio.wait_for(generator.started.wait(), 10)
        cancel = await case["client"].post(
            f"{case['base']}/image-jobs/{job['id']}/cancel", headers=case["headers"]
        )
        assert cancel.json()["cancel_requested"] is True
        done = await case["until"](job["id"], {"cancelled", "failed", "completed"}, 40)
        assert generator.stopped.is_set()
    assert done["status"] == "cancelled" and done["assets"] == []


@pytest.mark.skipif(
    not (
        os.getenv("FLINT_GRAPH_NARRATIVE_IMAGE_RUNTIME_DIR")
        and os.getenv("FLINT_GRAPH_NARRATIVE_IMAGE_MODEL_DIR")
        and os.getenv("FLINT_GRAPH_NARRATIVE_IMAGE_MODEL_MANIFEST_SHA256")
    ),
    reason="requires the isolated image runtime, a local model and its pinned manifest",
)
async def test_real_gpu_job_stores_verified_portraits(live_case):
    case = live_case
    python, script = runtime_paths(Path(os.environ["FLINT_GRAPH_NARRATIVE_IMAGE_RUNTIME_DIR"]))
    model_dir = Path(os.environ["FLINT_GRAPH_NARRATIVE_IMAGE_MODEL_DIR"])
    model = await asyncio.to_thread(
        verify_model, model_dir, os.environ["FLINT_GRAPH_NARRATIVE_IMAGE_MODEL_MANIFEST_SHA256"]
    )
    generator = LocalImageGenerator(
        python=python, script=script, model_dir=model_dir, model=model, deadline_seconds=600
    )
    # A shared GPU may hold the assistant's model; release it only when named explicitly.
    loaded = os.getenv("FLINT_GRAPH_NARRATIVE_IMAGE_RELEASE_OLLAMA_MODEL")
    releaser = OllamaGpuReleaser("http://127.0.0.1:11434", loaded) if loaded else None
    job = await case["generate"]("silver hair, amber eyes, navy coat", count=1)
    async with worker(case, generator, releaser):
        done = await case["until"](job["id"], {"completed", "failed"}, 900)
    assert done["status"] == "completed", done["error_code"]
    [asset] = done["assets"]
    content = await case["client"].get(
        f"{case['base']}/assets/{asset['id']}/content", headers=case["headers"]
    )
    assert hashlib.sha256(content.content).hexdigest() == asset["sha256"]
    assert (asset["width"], asset["height"]) == (832, 1216)

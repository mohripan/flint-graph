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
    verify_cutout_model,
    verify_model,
)
from flint_graph.main import app
from flint_graph.narrative.imagegen import HIRES_SCALE
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

        async def generate(appearance, count=2, **changes):
            response = await client.post(
                f"{base}/characters/mira/portrait-jobs",
                headers=headers,
                json={
                    "appearance": appearance,
                    "character_type": "girl",
                    "framing": "portrait",
                    "count": count,
                    "idempotency_key": str(uuid4()),
                    **changes,
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


# Alpha statistics read with the isolated runtime's own Pillow and NumPy.
ALPHA_PROBE = """
import json, sys
import numpy as np
from PIL import Image
image = Image.open(sys.argv[1])
alpha = np.asarray(image)[..., 3]
h, w = alpha.shape
print(json.dumps({
    "mode": image.mode,
    "corners": [int(alpha[y, x]) for y in (0, h - 1) for x in (0, w - 1)],
    "border_max": int(max(alpha[0].max(), alpha[-1].max(), alpha[:, 0].max(), alpha[:, -1].max())),
    "opaque": round(float((alpha == 255).mean()), 3),
    "clear": round(float((alpha == 0).mean()), 3),
    "centre_column_opaque": int((alpha[:, w // 2] == 255).sum()),
}))
"""


@pytest.mark.skipif(
    not (
        os.getenv("FLINT_GRAPH_NARRATIVE_IMAGE_RUNTIME_DIR")
        and os.getenv("FLINT_GRAPH_NARRATIVE_IMAGE_MODEL_DIR")
        and os.getenv("FLINT_GRAPH_NARRATIVE_IMAGE_MODEL_MANIFEST_SHA256")
        and os.getenv("FLINT_GRAPH_NARRATIVE_IMAGE_CUTOUT_MODEL_DIR")
        and os.getenv("FLINT_GRAPH_NARRATIVE_IMAGE_CUTOUT_MANIFEST_SHA256")
    ),
    reason="requires the isolated runtime, both local models and their pinned manifests",
)
@pytest.mark.parametrize("hires", [False, True], ids=["standard", "hires"])
async def test_real_gpu_transparent_job_stores_a_cut_out_sprite(live_case, tmp_path, hires):
    case = live_case
    runtime = Path(os.environ["FLINT_GRAPH_NARRATIVE_IMAGE_RUNTIME_DIR"])
    python, script = runtime_paths(runtime)
    model_dir = Path(os.environ["FLINT_GRAPH_NARRATIVE_IMAGE_MODEL_DIR"])
    model = await asyncio.to_thread(
        verify_model, model_dir, os.environ["FLINT_GRAPH_NARRATIVE_IMAGE_MODEL_MANIFEST_SHA256"]
    )
    cutout = await asyncio.to_thread(
        verify_cutout_model,
        Path(os.environ["FLINT_GRAPH_NARRATIVE_IMAGE_CUTOUT_MODEL_DIR"]),
        os.environ["FLINT_GRAPH_NARRATIVE_IMAGE_CUTOUT_MANIFEST_SHA256"],
    )
    generator = LocalImageGenerator(
        python=python,
        script=script,
        model_dir=model_dir,
        model=model,
        deadline_seconds=900,
        cutout=cutout,
    )
    loaded = os.getenv("FLINT_GRAPH_NARRATIVE_IMAGE_RELEASE_OLLAMA_MODEL")
    releaser = OllamaGpuReleaser("http://127.0.0.1:11434", loaded) if loaded else None
    job = await case["generate"](
        "silver hair in a low ponytail, amber eyes, weathered navy coat, calm smile",
        count=1,
        framing="full_body",
        transparent=True,
        hires=hires,
    )
    async with worker(case, generator, releaser):
        done = await case["until"](job["id"], {"completed", "failed"}, 1200)
    assert done["status"] == "completed", done["error_code"]
    output = (done["output_width"], done["output_height"])
    assert output == (
        (round(832 * HIRES_SCALE), round(1216 * HIRES_SCALE)) if hires else (832, 1216)
    )
    assert done["cutout"] == {
        "model": f"{cutout.identity.repo}@{cutout.identity.revision}",
        "sha256": cutout.sha256,
    }
    [asset] = done["assets"]
    assert asset["kind"] == "sprite" and asset["status"] == "candidate"
    content = await case["client"].get(
        f"{case['base']}/assets/{asset['id']}/content", headers=case["headers"]
    )
    assert hashlib.sha256(content.content).hexdigest() == asset["sha256"]
    left, top, right, bottom = asset["provenance"]["cutout"]["box"]
    assert (asset["width"], asset["height"]) == (right - left, bottom - top)
    assert right <= output[0] and bottom <= output[1]
    assert asset["height"] > (1216 if hires else 900), "A full-body figure fills the height"
    assert ("hires" in asset["provenance"]) == hires
    sprite = tmp_path / "sprite.png"
    await asyncio.to_thread(sprite.write_bytes, content.content)
    probe = await asyncio.create_subprocess_exec(
        str(python), "-I", "-c", ALPHA_PROBE, str(sprite), stdout=asyncio.subprocess.PIPE
    )
    stdout, _ = await probe.communicate()
    alpha = json.loads(stdout)
    assert alpha["mode"] == "RGBA" and alpha["corners"] == [0, 0, 0, 0]
    assert alpha["opaque"] > 0.1 and alpha["clear"] > 0.2 and alpha["centre_column_opaque"] > 100
    if save := os.getenv("FLINT_GRAPH_NARRATIVE_IMAGE_SAVE_DIR"):
        await asyncio.to_thread(_save_evidence, Path(save), content.content, done, alpha)


def _save_evidence(target: Path, data: bytes, job: dict, alpha: dict) -> None:
    """Keep the qualified sprite and its job record (operator-chosen, ignored path)."""
    name = hashlib.sha256(data).hexdigest()[:16]
    target.mkdir(parents=True, exist_ok=True)
    (target / f"{name}.png").write_bytes(data)
    (target / f"{name}.json").write_text(json.dumps({"job": job, "alpha": alpha}, indent=2))


DIFF_PROBE = """
import json, sys
import numpy as np
from PIL import Image
base = np.asarray(Image.open(sys.argv[1]).convert("RGBA")).astype(int)
out = np.asarray(Image.open(sys.argv[2]).convert("RGBA")).astype(int)
l, t, r, b = map(int, sys.argv[3].split(","))
side = round(max(r - l, b - t) * 2.4)
cx, cy = (l + r) / 2, (t + b) / 2
x0, y0 = round(cx - side / 2), round(cy - side / 2)
outside = np.ones(base.shape[:2], bool)
outside[max(0, y0):y0 + side, max(0, x0):x0 + side] = False
print(json.dumps({
    "same_size": base.shape == out.shape,
    "alpha_equal": bool((base[..., 3] == out[..., 3]).all()),
    "outside_changed": int((np.abs(base - out).max(axis=2)[outside] > 0).sum()),
    "face_change": round(float(np.abs(base[t:b, l:r, :3] - out[t:b, l:r, :3]).mean()), 2),
}))
"""


@pytest.mark.skipif(
    not (
        os.getenv("FLINT_GRAPH_NARRATIVE_IMAGE_RUNTIME_DIR")
        and os.getenv("FLINT_GRAPH_NARRATIVE_IMAGE_MODEL_DIR")
        and os.getenv("FLINT_GRAPH_NARRATIVE_IMAGE_MODEL_MANIFEST_SHA256")
        and os.getenv("FLINT_GRAPH_NARRATIVE_EXPRESSION_BASE")
        and os.getenv("FLINT_GRAPH_NARRATIVE_EXPRESSION_FACE_BOX")
    ),
    reason="requires the isolated runtime, the local model, a base sprite and its face box",
)
async def test_real_gpu_expressions_repaint_only_the_face(live_case, tmp_path):
    case = live_case
    python, script = runtime_paths(Path(os.environ["FLINT_GRAPH_NARRATIVE_IMAGE_RUNTIME_DIR"]))
    model_dir = Path(os.environ["FLINT_GRAPH_NARRATIVE_IMAGE_MODEL_DIR"])
    model = await asyncio.to_thread(
        verify_model, model_dir, os.environ["FLINT_GRAPH_NARRATIVE_IMAGE_MODEL_MANIFEST_SHA256"]
    )
    generator = LocalImageGenerator(
        python=python, script=script, model_dir=model_dir, model=model, deadline_seconds=900
    )
    base_bytes = await asyncio.to_thread(
        Path(os.environ["FLINT_GRAPH_NARRATIVE_EXPRESSION_BASE"]).read_bytes
    )
    box = [int(item) for item in os.environ["FLINT_GRAPH_NARRATIVE_EXPRESSION_FACE_BOX"].split(",")]
    client, headers, base = case["client"], case["headers"], case["base"]
    uploaded = await client.post(
        f"{base}/assets",
        headers=headers,
        data={"kind": "sprite", "name": "Base", "license": "openrail++", "notice": "",
              "rights_declared": "true"},
        files={"file": ("base.png", base_bytes, "image/png")},
    )
    assert uploaded.status_code == 201, uploaded.text
    profile = {"base_version": 0, "character_type": "girl", "framing": "full_body",
               "appearance": "shoulder-length silver hair, amber eyes, navy coat"}
    saved = await client.put(f"{base}/characters/mira", headers=headers, json=profile)
    assert saved.status_code == 200, saved.text
    expressions = ["happy", "angry", "sad", "surprised"]
    created = await client.post(
        f"{base}/characters/mira/expression-jobs",
        headers=headers,
        json={"base_asset_id": uploaded.json()["id"], "face_box": box,
              "expressions": expressions, "idempotency_key": str(uuid4())},
    )
    assert created.status_code == 202, created.text
    loaded = os.getenv("FLINT_GRAPH_NARRATIVE_IMAGE_RELEASE_OLLAMA_MODEL")
    releaser = OllamaGpuReleaser("http://127.0.0.1:11434", loaded) if loaded else None
    async with worker(case, generator, releaser):
        done = await case["until"](created.json()["id"], {"completed", "failed"}, 1200)
    assert done["status"] == "completed", done["error_code"]
    assert [asset["provenance"]["expression"] for asset in done["assets"]] == expressions
    original = tmp_path / "base.png"
    await asyncio.to_thread(original.write_bytes, base_bytes)
    results = {}
    for asset in done["assets"]:
        content = await client.get(f"{base}/assets/{asset['id']}/content", headers=headers)
        assert hashlib.sha256(content.content).hexdigest() == asset["sha256"]
        path = tmp_path / f"{asset['provenance']['expression']}.png"
        await asyncio.to_thread(path.write_bytes, content.content)
        probe = await asyncio.create_subprocess_exec(
            str(python), "-I", "-c", DIFF_PROBE, str(original), str(path), ",".join(map(str, box)),
            stdout=asyncio.subprocess.PIPE,
        )
        stdout, _ = await probe.communicate()
        result = json.loads(stdout)
        results[asset["provenance"]["expression"]] = result
        assert result["same_size"] and result["alpha_equal"], result
        assert result["outside_changed"] == 0, result
        assert result["face_change"] > 3, result
    if save := os.getenv("FLINT_GRAPH_NARRATIVE_IMAGE_SAVE_DIR"):
        target = Path(save)
        await asyncio.to_thread(target.mkdir, parents=True, exist_ok=True)
        for name in expressions:
            data = await asyncio.to_thread((tmp_path / f"{name}.png").read_bytes)
            await asyncio.to_thread((target / f"{name}.png").write_bytes, data)
        await asyncio.to_thread(
            (target / "job.json").write_text, json.dumps({"job": done, "checks": results}, indent=2)
        )

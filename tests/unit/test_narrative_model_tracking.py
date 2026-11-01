import json
from uuid import uuid4

import httpx

from flint_graph.infrastructure.narrative_model_tracking import ModelTracker


async def test_tracking_mirrors_only_explicit_numeric_metrics_and_hashes():
    calls = []

    def handle(request):
        calls.append((request.url.path, json.loads(request.content) if request.content else {}))
        if request.url.path.endswith("get-by-name"):
            return httpx.Response(200, json={"experiment": {"experiment_id": "1"}})
        if request.url.path.endswith("create"):
            return httpx.Response(200, json={"run": {"info": {"run_id": "a" * 32}}})
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        tracker = ModelTracker("http://localhost:6096", client=client)
        result = await tracker.record(
            job_id=uuid4(),
            base_hash="b" * 64,
            dataset_hash="c" * 64,
            recipe_hash="d" * 64,
            weights_hash="e" * 64,
            losses=[1.2, 0.8],
            runtime={"seconds": "10", "host_rss_bytes": "100", "secret": "do not upload"},
            image_count=4,
        )
    assert result == "a" * 32
    wire = json.dumps(calls)
    assert "do not upload" not in wire and "secret" not in wire
    batch = next(body for path, body in calls if path.endswith("log-batch"))
    assert [m["value"] for m in batch["metrics"] if m["key"] == "loss"] == [1.2, 0.8]
    assert calls[-1][1]["status"] == "FINISHED"


async def test_tracking_outage_never_fails_training():
    def offline(request):
        raise httpx.ConnectError("private endpoint", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(offline)) as client:
        result = await ModelTracker("http://localhost:6096", client=client).record(
            job_id=uuid4(),
            base_hash="b" * 64,
            dataset_hash="c" * 64,
            recipe_hash="d" * 64,
            weights_hash="e" * 64,
            losses=[1.0],
            runtime={},
            image_count=4,
        )
    assert result is None


async def test_character_training_uses_a_separate_allowlisted_experiment():
    requests = []

    def handle(request):
        requests.append(request)
        if request.url.path.endswith("get-by-name"):
            return httpx.Response(200, json={"experiment": {"experiment_id": "2"}})
        if request.url.path.endswith("create"):
            return httpx.Response(200, json={"run": {"info": {"run_id": "c" * 32}}})
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await ModelTracker("http://localhost:6096", client=client).record(
            job_id=uuid4(),
            base_hash="a" * 64,
            dataset_hash="b" * 64,
            recipe_hash="d" * 64,
            weights_hash="e" * 64,
            losses=[0.5],
            runtime={},
            image_count=4,
            kind="character_look",
        )
    assert result == "c" * 32
    assert requests[0].url.params["experiment_name"] == "flint-character-look"
    batch = next(json.loads(r.content) for r in requests if r.url.path.endswith("log-batch"))
    assert {"key": "kind", "value": "character_look"} in batch["params"]

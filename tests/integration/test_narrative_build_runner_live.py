"""Owned actual host runner; default runs do not discover/pull/start a builder."""

import asyncio
import hashlib
import io
import json
import os
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

import pytest

from flint_graph.infrastructure.narrative_builder import DockerNarrativeBuilder
from flint_graph.narrative.package import load_text_package


def configured(tmp_path):
    image = os.environ.get("FLINT_GRAPH_NARRATIVE_BUILDER_IMAGE")
    pin = os.environ.get("FLINT_GRAPH_NARRATIVE_BUILDER_TOOLCHAIN")
    if not image or not pin:
        pytest.skip("Explicit owned Linux builder image/toolchain required")
    story = {
        "schema_version": "1",
        "id": "original",
        "title": "Original runner fixture",
        "language": "en",
        "entry": "end",
        "characters": {},
        "variables": {},
        "assets": {},
        "nodes": {
            "end": {
                "type": "end",
                "text_id": "end_text",
                "ending": "quiet",
                "text": "A quiet ending.",
            }
        },
    }
    package = load_text_package(json.dumps(story).encode(), b"Original fixture. CC0.\n")
    runner = DockerNarrativeBuilder(image=image, toolchain_sha256=pin, work_root=tmp_path)
    return runner, package


async def running(execution, *, include_stopped=False):
    states = ["--all"] if include_stopped else []
    process = await asyncio.create_subprocess_exec(
        "docker",
        "ps",
        *states,
        "--filter",
        "label=io.flintgraph.narrative.execution=" + str(execution),
        "--format",
        "{{.ID}}",
        stdout=asyncio.subprocess.PIPE,
    )
    output, _ = await process.communicate()
    assert process.returncode == 0
    return bool(output.strip())


@pytest.mark.anyio
async def test_actual_host_runner_returns_licensed_verified_zips_and_cleans_owned_scratch(tmp_path):
    runner, package = configured(tmp_path)

    async def current():
        pass

    execution = uuid4()
    result = await runner.build(package, execution_id=execution, check=current)
    assert result.package_hash == package.content_hash
    assert list(tmp_path.iterdir()) == []
    assert not await running(execution, include_stopped=True)
    with ZipFile(io.BytesIO(result.source_zip)) as source:
        assert source.read("content/story.json") == package.canonical_story
        manifest = json.loads(source.read("build-manifest.json"))
        assert manifest["package_hash"] == package.content_hash
        for name, expected in manifest["files"].items():
            assert hashlib.sha256(source.read(name)).hexdigest() == expected
        assert len(source.namelist()) == 19
    with ZipFile(io.BytesIO(result.web_zip)) as web:
        assert "index.wasm" in web.namelist()
        assert web.read("NOTICES.txt") == package.notices
        assert b"SIL OPEN FONT LICENSE" in web.read("LICENSE-Lora.txt")
        assert "GODOT-NOTICE.txt" in web.namelist()
        assert len(web.namelist()) == 12
    evidence = os.environ.get("FLINT_GRAPH_NARRATIVE_RUNNER_EVIDENCE_DIR")
    if evidence:
        output = Path(evidence)
        await asyncio.to_thread(output.mkdir)
        (output / "source.zip").write_bytes(result.source_zip)
        (output / "web.zip").write_bytes(result.web_zip)
        receipt = {
            "package_hash": package.content_hash,
            "image": runner.image,
            "toolchain_sha256": runner.toolchain,
            "source_sha256": hashlib.sha256(result.source_zip).hexdigest(),
            "web_sha256": hashlib.sha256(result.web_zip).hexdigest(),
            "source_bytes": len(result.source_zip),
            "web_bytes": len(result.web_zip),
            "owned_scratch_removed": True,
            "owned_running_child_removed": True,
        }
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")


@pytest.mark.anyio
async def test_actual_task_cancellation_stops_owned_engine_and_preserves_sibling_files(tmp_path):
    runner, package = configured(tmp_path)
    retained = tmp_path / "unrelated.txt"
    retained.write_bytes(b"must survive")

    async def current():
        pass

    execution = uuid4()
    task = asyncio.create_task(runner.build(package, execution_id=execution, check=current))
    try:
        async with asyncio.timeout(20):
            while not await running(execution):
                if task.done():
                    await task
                    pytest.fail("Build finished before cancellation qualification")
                await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    assert not await running(execution, include_stopped=True)
    assert list(tmp_path.iterdir()) == [retained]
    assert retained.read_bytes() == b"must survive"

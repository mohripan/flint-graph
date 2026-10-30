import asyncio
import csv
import io
import json
import os
import signal
import subprocess
import sys
import tracemalloc
from pathlib import Path
from uuid import uuid4

import pytest

from flint_graph.infrastructure.narrative_builder import BuildError, DockerNarrativeBuilder
from flint_graph.narrative.package import load_text_package

STORY = (
    b'{"schema_version":"1","id":"original","title":"Original","language":"en",'
    b'"entry":"end","characters":{},"variables":{},"assets":{},"nodes":{"end":'
    b'{"type":"end","text_id":"end_text","ending":"quiet","text":"The end."}}}'
)


@pytest.mark.anyio
async def test_cancelled_before_preparation_never_touches_scratch_or_launches_docker(tmp_path):
    retained = tmp_path / "unrelated.txt"
    retained.write_bytes(b"must remain")
    runner = DockerNarrativeBuilder(
        image="sha256:" + "a" * 64,
        toolchain_sha256="b" * 64,
        work_root=tmp_path,
        docker_command=("NONEXISTENT_DOCKER_MUST_NOT_RUN",),
    )

    async def denied():
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await runner.build(load_text_package(STORY), execution_id=uuid4(), check=denied)
    assert list(tmp_path.iterdir()) == [retained]
    assert retained.read_bytes() == b"must remain"


@pytest.mark.parametrize("image,toolchain", [("latest", "b" * 64), ("sha256:" + "a" * 64, "bad")])
def test_mutable_or_invalid_builder_identity_is_rejected_before_any_work(
    tmp_path, image, toolchain
):
    with pytest.raises(ValueError, match=r"^Invalid narrative builder identity$"):
        DockerNarrativeBuilder(image=image, toolchain_sha256=toolchain, work_root=Path(tmp_path))


@pytest.mark.anyio
@pytest.mark.parametrize("stream", ["stdout", "stderr"])
async def test_unbounded_cli_output_fails_safely_without_retaining_or_exposing_it(tmp_path, stream):
    script = tmp_path / "owned_cli_fixture.py"
    script.write_text(
        f"import sys; sys.{stream}.buffer.write(b'PRIVATE_CANARY' + b'x' * (8*1024*1024))",
        encoding="utf-8",
    )
    scratch = tmp_path / "scratch"
    await asyncio.to_thread(scratch.mkdir)
    runner = DockerNarrativeBuilder(
        image="sha256:" + "a" * 64,
        toolchain_sha256="b" * 64,
        work_root=scratch,
        docker_command=(sys.executable, str(script)),
    )

    async def current():
        pass

    tracemalloc.start()
    try:
        with pytest.raises(BuildError, match=r"^build_io$"):
            await runner.build(load_text_package(STORY), execution_id=uuid4(), check=current)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 4 * 1024 * 1024
    assert list(scratch.iterdir()) == []


def external_fixture(tmp_path, mode):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    script = Path(__file__).parents[1] / "fixtures/narrative/owned_docker_cli.py"
    runner = DockerNarrativeBuilder(
        image="sha256:" + "a" * 64,
        toolchain_sha256="b" * 64,
        work_root=scratch,
        docker_command=(sys.executable, str(script), str(tmp_path), mode),
    )
    return runner, scratch


async def current():
    pass


@pytest.mark.anyio
async def test_recovery_cleans_exact_token_without_loading_original_image(tmp_path):
    runner, scratch = external_fixture(tmp_path, "normal")
    execution = uuid4()
    folder = scratch / ("build-" + execution.hex + "-recovered")
    folder.mkdir()
    (folder / ".owner").write_text(str(execution), encoding="ascii")
    (folder / "private.txt").write_bytes(b"PRIVATE SOURCE")
    sibling = scratch / "creator-export"
    sibling.mkdir()
    (sibling / "game.txt").write_bytes(b"creator owned")
    (tmp_path / "state.json").write_text(json.dumps({"execution": str(execution)}))
    await runner.cleanup_execution(execution)
    await runner.cleanup_execution(execution)
    assert not folder.exists()
    assert (sibling / "game.txt").read_bytes() == b"creator owned"
    assert not (tmp_path / "state.json").exists()


@pytest.mark.anyio
async def test_recovery_refuses_unverified_scratch_before_removing_any_container(tmp_path):
    runner, scratch = external_fixture(tmp_path, "normal")
    execution = uuid4()
    folder = scratch / ("build-" + execution.hex + "-unverified")
    folder.mkdir()
    (folder / ".owner").write_text(str(uuid4()), encoding="ascii")
    (tmp_path / "state.json").write_text(json.dumps({"execution": str(execution)}))
    with pytest.raises(BuildError, match="build_io"):
        await runner.cleanup_execution(execution)
    assert folder.exists() and (tmp_path / "state.json").exists()


def managed_record(scratch, execution, expires, image="sha256:" + "a" * 64):
    folder = scratch / ("build-" + execution.hex + "-recovered")
    folder.mkdir()
    (folder / ".owner").write_text(str(execution), encoding="ascii")
    record = {
        "schema_version": "1",
        "execution_id": str(execution),
        "expires_at": expires,
        "image": image,
        "toolchain_sha256": "b" * 64,
    }
    (folder / ".execution.json").write_text(
        json.dumps(record, sort_keys=True, separators=(",", ":"))
    )
    return folder


@pytest.mark.anyio
async def test_expired_sweep_only_removes_verified_managed_execution(tmp_path):
    runner, scratch = external_fixture(tmp_path, "normal")
    expired, live = uuid4(), uuid4()
    old = managed_record(scratch, expired, 1)
    fresh = managed_record(scratch, live, 9999999999)
    unrelated = scratch / "creator-export"
    unrelated.mkdir()
    (unrelated / "keep.txt").write_bytes(b"creator owned")
    (tmp_path / "state.json").write_text(json.dumps({"execution": str(expired), "expires": "1"}))
    assert await runner.sweep_expired() == 1
    assert not old.exists() and fresh.exists()
    assert (unrelated / "keep.txt").read_bytes() == b"creator owned"
    assert await runner.sweep_expired() == 0


@pytest.mark.anyio
async def test_sweep_refuses_metadata_container_identity_mismatch(tmp_path):
    runner, scratch = external_fixture(tmp_path, "normal")
    execution = uuid4()
    old = managed_record(scratch, execution, 1, image="sha256:" + "e" * 64)
    (tmp_path / "state.json").write_text(json.dumps({"execution": str(execution), "expires": "1"}))
    assert await runner.sweep_expired() == 0
    assert old.exists() and (tmp_path / "state.json").exists()


@pytest.mark.anyio
async def test_sweep_progresses_past_a_thousand_retained_siblings(tmp_path, monkeypatch):
    runner, scratch = external_fixture(tmp_path, "normal")
    for index in range(1000):
        (scratch / f"000-retained-{index:04}").write_bytes(b"retain")
    execution = uuid4()
    old = managed_record(scratch, execution, 1)
    (tmp_path / "state.json").write_text(json.dumps({"execution": str(execution), "expires": "1"}))
    native_scandir = os.scandir

    class OrderedScan:
        def __init__(self, native):
            self.native = native
            self.entries = iter(sorted(native, key=lambda entry: entry.name))

        def __iter__(self):
            return self

        def __next__(self):
            return next(self.entries)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.native.close()

    def ordered_scandir(path):
        # Only the external root enumeration order is fixed. Other paths/FDs
        # retain their native iterator/context-manager behavior for shutil.
        scan = native_scandir(path)
        return OrderedScan(scan) if path == scratch else scan

    monkeypatch.setattr(os, "scandir", ordered_scandir)
    assert await runner.sweep_expired() == 0
    assert old.exists()
    assert await runner.sweep_expired() == 1
    assert not old.exists()
    assert len(list(scratch.iterdir())) == 1000


def process_alive(pid):
    if sys.platform == "win32":
        result = subprocess.check_output(
            ["tasklist", "/FO", "CSV", "/NH", "/FI", f"PID eq {pid}"],
            text=True,
        )
        return any(len(row) > 1 and row[1] == str(pid) for row in csv.reader(io.StringIO(result)))
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


@pytest.mark.anyio
async def test_create_failure_preserves_original_error_and_removes_private_input(tmp_path):
    runner, scratch = external_fixture(tmp_path, "create_failure")
    with pytest.raises(BuildError, match=r"^build_io$"):
        await runner.build(load_text_package(STORY), execution_id=uuid4(), check=current)
    assert list(scratch.iterdir()) == []


@pytest.mark.anyio
async def test_corrupted_source_manifest_is_rejected_before_creating_a_child(tmp_path, monkeypatch):
    runner, scratch = external_fixture(tmp_path, "create_failure")
    original = Path.read_bytes

    def read(path):
        data = original(path)
        if path.name == "build-manifest.json" and path.parent.name == "input":
            manifest = json.loads(data)
            manifest["package_hash"] = "f" * 64
            return json.dumps(manifest).encode()
        return data

    monkeypatch.setattr(Path, "read_bytes", read)
    with pytest.raises(BuildError, match=r"^artifact_invalid$"):
        await runner.build(load_text_package(STORY), execution_id=uuid4(), check=current)
    assert list(scratch.iterdir()) == []
    assert not (tmp_path / "state.json").exists()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "mode,marker", [("cleanup_delay", "cleanup-entered"), ("stalled_archive", "archive-entered")]
)
async def test_cancellation_joins_cleanup_and_stalled_archive_reader(tmp_path, mode, marker):
    runner, scratch = external_fixture(tmp_path, mode)
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()
    unhandled = []
    loop.set_exception_handler(lambda _, context: unhandled.append(context))
    task = asyncio.create_task(
        runner.build(load_text_package(STORY), execution_id=uuid4(), check=current)
    )
    try:
        async with asyncio.timeout(10):
            while not await asyncio.to_thread((tmp_path / marker).exists):
                if task.done():
                    await task
                    pytest.fail("CLI fixture did not reach the selected fault")
                await asyncio.sleep(0.01)
        task.cancel()
        asyncio.get_running_loop().call_soon(task.cancel)
        for _ in range(25):
            if task.done():
                break
            await asyncio.sleep(0.001)
            task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(task), timeout=2)
        assert list(scratch.iterdir()) == []
        assert not (tmp_path / "state.json").exists()
        pid = int((tmp_path / "archive-cli.pid").read_text())
        assert not await asyncio.to_thread(process_alive, pid)
        await asyncio.sleep(0.02)
        assert unhandled == []
    finally:
        loop.set_exception_handler(previous_handler)
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        marker = tmp_path / "descendant.pid"
        if marker.exists():
            try:
                os.kill(int(marker.read_text()), signal.SIGTERM)
            except ProcessLookupError:
                pass

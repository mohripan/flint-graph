import pytest
from pydantic import ValidationError

from flint_graph.config import Settings


def test_narrative_processes_are_opt_in_and_worker_requires_private_root_and_pins(tmp_path):
    default = Settings(env="test")
    assert not default.narrative_worker_enabled and not default.narrative_relay_enabled
    with pytest.raises(ValidationError, match="narrative worker requires"):
        Settings(env="test", narrative_worker_enabled=True)
    configured = Settings(
        env="test",
        narrative_worker_enabled=True,
        narrative_build_work_root=str(tmp_path),
        narrative_release_builder_image_digest="sha256:" + "a" * 64,
        narrative_release_toolchain_sha256="b" * 64,
    )
    assert configured.narrative_task_queue == "narrative-build"
    # API admission is independent; a worker can drain accepted work while it is disabled.
    assert not configured.narrative_releases_enabled


def test_narrative_dispatch_cannot_share_ingestion_queue():
    with pytest.raises(ValidationError, match="separate narrative task queue"):
        Settings(env="test", narrative_relay_enabled=True, narrative_task_queue="ingestion")


@pytest.mark.anyio
async def test_disabled_operator_entry_points_reject_before_connecting():
    from flint_graph.processes.narrative_relay import run_forever
    from flint_graph.processes.narrative_worker import run_worker

    with pytest.raises(SystemExit, match="narrative worker is disabled"):
        await run_worker(Settings(env="test"))
    with pytest.raises(SystemExit, match="narrative relay is disabled"):
        await run_forever(Settings(env="test"))


def test_image_cutout_needs_an_absolute_model_directory_and_its_manifest_pin(tmp_path):
    base = {
        "env": "test",
        "narrative_image_worker_enabled": True,
        "narrative_image_runtime_dir": str(tmp_path),
        "narrative_image_model_dir": str(tmp_path),
        "narrative_image_model_manifest_sha256": "a" * 64,
    }
    assert Settings(**base).narrative_image_cutout_model_dir is None, "Cutout is optional"
    configured = Settings(
        **base,
        narrative_image_cutout_model_dir=str(tmp_path / "anime-seg"),
        narrative_image_cutout_manifest_sha256="b" * 64,
    )
    assert configured.narrative_image_cutout_manifest_sha256 == "b" * 64
    for partial in (
        {"narrative_image_cutout_model_dir": str(tmp_path)},
        {"narrative_image_cutout_manifest_sha256": "b" * 64},
        {
            "narrative_image_cutout_model_dir": "anime-seg",
            "narrative_image_cutout_manifest_sha256": "b" * 64,
        },
    ):
        with pytest.raises(ValidationError, match="cutout"):
            Settings(**base, **partial)

from pathlib import Path

import pytest
from pydantic import ValidationError

from flint_graph.config import Settings


def test_style_worker_requires_explicit_runtime_model_pin_and_separate_queue():
    with pytest.raises(ValidationError, match="style"):
        Settings(_env_file=None, env="test", narrative_style_worker_enabled=True)
    values = dict(
        narrative_style_worker_enabled=True,
        narrative_style_runtime_dir=str(Path.cwd() / "runtimes/stylegen"),
        narrative_pose_runtime_dir=str(Path.cwd() / "runtimes/posegen"),
        narrative_pose_model_dir=str(Path.cwd() / "model"),
        narrative_pose_model_manifest_sha256="a" * 64,
    )
    assert Settings(_env_file=None, env="test", **values).narrative_style_worker_enabled
    with pytest.raises(ValidationError, match="style"):
        Settings(_env_file=None, env="test", **values, narrative_style_task_queue="narrative-pose")


@pytest.mark.parametrize(
    "url",
    [
        "file:///private",
        "ftp://localhost",
        "http://user:secret@localhost:6096",
        "http://localhost:6096/?key=secret",
    ],
)
def test_model_tracking_endpoint_is_an_operator_http_origin(url):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, env="test", narrative_model_tracking_url=url)

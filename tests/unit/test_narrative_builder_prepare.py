import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from flint_graph.narrative.export import TEMPLATE_FILES


def test_operator_preparation_rejects_unqualified_engine_before_creating_context(tmp_path):
    engine = tmp_path / "unqualified"
    engine.write_bytes(b"not the pinned engine")
    templates = tmp_path / "templates"
    templates.mkdir()
    output = tmp_path / "context"
    tool = Path(__file__).parents[2] / "tools/narrative/prepare_builder.py"
    result = subprocess.run(
        [
            sys.executable,
            str(tool),
            "--engine",
            str(engine),
            "--templates",
            str(templates),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert "unqualified_engine" in result.stderr
    assert not output.exists()


def test_source_replacement_during_copy_cannot_receive_a_valid_toolchain_receipt(
    tmp_path, monkeypatch
):
    spec = importlib.util.spec_from_file_location(
        "builder_prepare", Path(__file__).parents[2] / "tools/narrative/prepare_builder.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    repository = tmp_path / "repository"
    files = [
        *("runtimes/godot/" + name for name in TEMPLATE_FILES),
        "src/flint_graph/narrative/build_child.py",
        "ops/narrative/Dockerfile",
    ]
    for name in files:
        target = repository / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"trusted fixture bytes")
    engine = tmp_path / "engine"
    engine.write_bytes(b"pinned original engine fixture")
    templates = tmp_path / "templates"
    templates.mkdir()
    pin = {"engine_sha256": hashlib.sha256(engine.read_bytes()).hexdigest(), "templates": {}}
    (repository / "ops/narrative/toolchain-linux.json").write_text(json.dumps(pin))
    monkeypatch.setattr(module, "ROOT", repository)
    original_copy = module.shutil.copyfile

    def replace_before_copy(source, target):
        if source == engine:
            engine.write_bytes(b"replaced after validation")
        return original_copy(source, target)

    monkeypatch.setattr(module.shutil, "copyfile", replace_before_copy)
    output = tmp_path / "context"
    with pytest.raises(ValueError, match=r"^copied_input_changed$"):
        module.prepare(engine, templates, output)
    assert not (output / "toolchain.json").exists()

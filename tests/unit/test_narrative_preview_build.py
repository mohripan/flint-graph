"""Which editor may host a playtest, and which engines may build one."""

import hashlib
import importlib.util
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


def _load(path: Path, name: str):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


build = _load(ROOT / "tools/narrative/build_preview.py", "build_preview")
toolchain = _load(ROOT / "ops/deploy/playtest_toolchain.py", "playtest_toolchain")


@pytest.mark.parametrize(
    "origin",
    ["http://localhost:5173", "https://flintgraph.digital", "https://studio.example.com:8443"],
)
def test_a_local_or_https_editor_may_host_a_playtest(origin):
    assert build.checked_parent(origin) == origin


@pytest.mark.parametrize(
    "origin",
    [
        "http://flintgraph.digital",
        "http://localhost",
        "https://flintgraph.digital/",
        "https://flintgraph.digital/studio",
        "https://flintgraph.digital?x=1",
        "https://user:secret@flintgraph.digital",
        "https://*.flintgraph.digital",
        "https://flintgraph.digital https://evil.example.com",
        "https://flintgraph.digital;script-src *",
        "*",
        "",
    ],
)
def test_nothing_else_may_because_the_origin_goes_into_a_security_header(origin):
    with pytest.raises(ValueError):
        build.checked_parent(origin)


def test_an_engine_is_held_to_the_pin_for_its_platform(tmp_path):
    runtime = json.loads((ROOT / "runtimes/godot/toolchain.json").read_bytes())
    linux = json.loads((ROOT / "ops/narrative/toolchain-linux.json").read_bytes())
    assert (
        build.pinned_engine(build.WINDOWS_ENGINE)
        == (runtime["extracted_sha256"][build.WINDOWS_ENGINE])
    )
    assert build.pinned_engine(build.LINUX_ENGINE) == linux["engine_sha256"]
    with pytest.raises(ValueError):
        build.pinned_engine("godot-from-somewhere-else")


def test_both_platforms_pin_the_same_templates():
    runtime = json.loads((ROOT / "runtimes/godot/toolchain.json").read_bytes())
    linux = json.loads((ROOT / "ops/narrative/toolchain-linux.json").read_bytes())
    for name, value in linux["templates"].items():
        assert runtime["extracted_sha256"][name] == value


def _archive(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return path


def test_only_the_named_member_is_taken_from_an_archive_and_its_hash_is_checked(tmp_path):
    source = _archive(tmp_path / "a.zip", {"good": b"engine", "other": b"never extracted"})
    target = tmp_path / "out" / "good"
    target.parent.mkdir()
    toolchain.extract(source, "good", hashlib.sha256(b"engine").hexdigest(), target)
    assert target.read_bytes() == b"engine"
    assert [path.name for path in target.parent.iterdir()] == ["good"]
    with pytest.raises(SystemExit):
        toolchain.extract(source, "good", "0" * 64, tmp_path / "out" / "again")
    with pytest.raises(KeyError):
        toolchain.extract(source, "missing", "0" * 64, tmp_path / "out" / "none")


def test_a_download_with_the_wrong_hash_is_refused(tmp_path, monkeypatch):
    def fake_open(url, timeout):
        return io.BytesIO(b"tampered")

    monkeypatch.setattr(toolchain.urllib.request, "urlopen", fake_open)
    with pytest.raises(SystemExit):
        toolchain.download("https://example.com/a.zip", tmp_path / "a.zip", "0" * 64, "0" * 128)
    assert not (tmp_path / "a.zip").exists()

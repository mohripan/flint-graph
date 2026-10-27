import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from flint_graph.narrative import load_package
from flint_graph.narrative.export import ExportError, export_godot

FIXTURE = Path(__file__).parents[1] / "fixtures/narrative/lantern_archive"


def test_creator_can_export_a_new_editable_godot_project(tmp_path: Path) -> None:
    package = load_package(FIXTURE)
    target = tmp_path / "my-game"

    result = export_godot(package, target)

    assert (target / "project.godot").is_file()
    assert (target / "runtime/bootstrap.gd").is_file()
    assert (target / "content/story.json").read_bytes() == package.canonical_story
    assert (target / "content/NOTICES.txt").read_bytes() == package.notices
    for asset in package.assets:
        assert (target / "content" / asset.path).read_bytes() == asset.data
    manifest = json.loads((target / "build-manifest.json").read_bytes())
    assert manifest["package_hash"] == package.content_hash
    assert manifest["godot_version"] == "4.7.2.stable"
    assert result.package_hash == package.content_hash


@pytest.mark.parametrize("nonempty", [False, True])
def test_export_never_replaces_an_existing_creator_directory(
    tmp_path: Path, nonempty: bool
) -> None:
    target = tmp_path / "existing"
    target.mkdir()
    if nonempty:
        (target / "custom.gd").write_bytes(b"creator customization")

    with pytest.raises(ExportError, match="output_exists"):
        export_godot(load_package(FIXTURE), target)

    assert list(target.iterdir()) == ([target / "custom.gd"] if nonempty else [])


def test_export_hashes_are_reproducible_and_cover_every_owned_file(tmp_path: Path) -> None:
    package = load_package(FIXTURE)
    first = export_godot(package, tmp_path / "first")
    second = export_godot(package, tmp_path / "second")

    assert first.manifest_hash == second.manifest_hash
    manifest = json.loads((tmp_path / "first/build-manifest.json").read_bytes())
    for relative, digest in manifest["files"].items():
        assert hashlib.sha256((tmp_path / "first" / relative).read_bytes()).hexdigest() == digest
    assert not any(".env" in path or "notes/" in path for path in manifest["files"])


def test_export_uses_captured_assets_instead_of_reopening_source_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    shutil.copytree(FIXTURE, source)
    package = load_package(source)
    before = package.assets[0].data
    (source / package.assets[0].path).write_bytes(b"changed after validation")

    export_godot(package, tmp_path / "exported")

    assert (tmp_path / "exported/content" / package.assets[0].path).read_bytes() == before


def test_missing_output_parent_is_safe_and_does_not_create_a_tree(tmp_path: Path) -> None:
    target = tmp_path / "missing" / "new-game"

    with pytest.raises(ExportError, match="export_io"):
        export_godot(load_package(FIXTURE), target)

    assert not (tmp_path / "missing").exists()


def test_failed_export_retains_host_modified_partial_output(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "new-game"
    original_open = Path.open

    def filesystem_open(path: Path, *args, **kwargs):
        if path == target / "content/story.json" and args and args[0] == "xb":
            (target / "GODOT-NOTICE.txt").write_bytes(b"creator replacement")
            raise OSError("Injected disk failure")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", filesystem_open)

    with pytest.raises(ExportError):
        export_godot(load_package(FIXTURE), target)

    assert (target / "GODOT-NOTICE.txt").read_bytes() == b"creator replacement"
    assert not (target / "build-manifest.json").exists()


def test_export_refuses_a_linked_output_parent(tmp_path: Path) -> None:
    actual = tmp_path / "actual"
    actual.mkdir()
    alias = tmp_path / "alias"
    if sys.platform == "win32":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(alias), str(actual)], capture_output=True, check=False
        )
        if result.returncode != 0:
            pytest.skip("Host does not permit local junction creation")
    else:
        alias.symlink_to(actual, target_is_directory=True)
    try:
        with pytest.raises(ExportError, match="unsafe_output_path"):
            export_godot(load_package(FIXTURE), alias / "game")
        assert list(actual.iterdir()) == []
    finally:
        if sys.platform == "win32":
            alias.rmdir()
        else:
            alias.unlink()

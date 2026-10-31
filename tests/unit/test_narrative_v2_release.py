"""Story package v2 in exports and release builds (ADR 0040 slice 3)."""

import hashlib
import io
import json
import os
import struct
import sys
import tomllib
import zipfile
import zlib
from pathlib import Path
from uuid import uuid4

import pytest

from flint_graph.application.services.narrative_releases import BuildIdentity
from flint_graph.infrastructure.narrative_builder import BuildError, DockerNarrativeBuilder
from flint_graph.narrative.build_child import RUNTIME_FILES, run_build
from flint_graph.narrative.export import TEMPLATE_FILES, export_godot
from flint_graph.narrative.package import attach_assets, load_text_package
from flint_graph.narrative.release_artifacts import (
    SOURCE_LIMITS,
    ArtifactError,
    ArtifactLimits,
    make_artifact_zip,
)
from flint_graph.narrative.values import PackageError
from flint_graph.narrative.wav import canonical_wav

ROOT = Path(__file__).parents[2]
MIB = 1024 * 1024


def png(width=4, height=6):
    def chunk(kind, payload):
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload))
        )

    row = b"\x00" + bytes([200, 80, 40, 255]) * width
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )


def font():
    tables = {tag: b"x" * 8 for tag in (b"cmap", b"glyf", b"head", b"loca", b"name")}
    tables[b"OS/2"] = b"\x00" * 16
    header = b"\x00\x01\x00\x00" + struct.pack(">HHHH", len(tables), 16, 4, 0)
    offset, directory, body = 12 + 16 * len(tables), b"", b""
    for tag in sorted(tables):
        directory += tag + struct.pack(">III", 0, offset + len(body), len(tables[tag]))
        body += tables[tag]
    return header + directory + body


DUSK, MIRA, TYPE = png(8, 4), png(3, 6), font()
HI = canonical_wav(1, 24000, struct.pack("<h", 16) * 2400)  # A voice clip (ADR 0043).


def sha(data):
    return hashlib.sha256(data).hexdigest()


def story():
    return {
        "schema_version": "2",
        "id": "harbor",
        "title": "Harbor",
        "language": "en",
        "entry": "s0",
        "characters": {"mira": {"name": "Mira", "sprites": {"neutral": "mira"}}},
        "variables": {},
        "assets": {
            "dusk": {"kind": "image", "path": "assets/dusk.png", "sha256": sha(DUSK)},
            "mira": {"kind": "image", "path": "assets/mira.png", "sha256": sha(MIRA)},
            "type": {"kind": "font", "path": "assets/type.ttf", "sha256": sha(TYPE)},
            "hi": {"kind": "audio", "path": "assets/hi.wav", "sha256": sha(HI)},
        },
        "theme": {"font": {"asset": "type", "size": 24}},
        "nodes": {
            "s0": {
                "type": "stage",
                "background": "dusk",
                "show": [{"character": "mira", "sprite": "neutral", "position": "left"}],
                "next": "l1",
            },
            "l1": {
                "type": "line",
                "speaker": "mira",
                "text_id": "l1",
                "text": "Hi.",
                "voice": {"mode": "full", "audio": "hi"},
                "next": "e",
            },
            "e": {"type": "end", "text_id": "e", "text": "Fin", "ending": "quiet"},
        },
    }


BYTES = {"dusk": DUSK, "mira": MIRA, "type": TYPE, "hi": HI}


def referencing(value=None):
    return load_text_package(
        json.dumps(value or story()).encode(), b"Notices.\n", allow_asset_refs=True
    )


def test_attach_assets_rechecks_every_asset_and_keeps_the_package_identity():
    package = referencing()
    attached = attach_assets(package, BYTES)
    assert attached.content_hash == package.content_hash
    assert {asset.id: asset.data for asset in attached.assets} == BYTES
    for broken, code in [
        ({**BYTES, "dusk": MIRA}, "hash_mismatch"),
        ({key: value for key, value in BYTES.items() if key != "type"}, "missing_file"),
        ({**BYTES, "extra": DUSK}, "missing_file"),
    ]:
        with pytest.raises(PackageError) as raised:
            attach_assets(package, broken)
        assert raised.value.code == code
    # A font named .otf must be an OpenType file; a TrueType one is refused.
    otf = story()
    otf["assets"]["type"]["path"] = "assets/type.otf"
    with pytest.raises(PackageError, match="unsafe_path"):
        attach_assets(referencing(otf), BYTES)
    not_png = story()
    not_png["assets"]["dusk"]["sha256"] = sha(b"not a png")
    with pytest.raises(PackageError):
        attach_assets(referencing(not_png), {**BYTES, "dusk": b"not a png"})


def test_v2_export_ships_fonts_and_images_with_keep_remaps(tmp_path):
    package = attach_assets(referencing(), BYTES)
    export_godot(package, tmp_path / "game")
    game = tmp_path / "game"
    assert (game / "content/assets/type.ttf").read_bytes() == TYPE
    remap = (game / "content/assets/type.ttf.import").read_text()
    assert 'importer="keep"' in remap and "res://content/assets/type.ttf" in remap
    assert "runtime/vn_view.gd" in TEMPLATE_FILES and RUNTIME_FILES == set(TEMPLATE_FILES)
    presets = (game / "export_presets.cfg").read_text()
    assert "content/assets/*.ttf" in presets and "content/assets/*.otf" in presets
    assert "content/assets/*.wav" in presets
    assert (game / "content/assets/hi.wav").read_bytes() == HI
    assert 'importer="keep"' in (game / "content/assets/hi.wav.import").read_text()
    manifest = json.loads((game / "build-manifest.json").read_bytes())
    assert manifest["runtime_version"] == "0.7.0"
    assert {"content/assets/dusk.png", "content/assets/type.ttf.import"} <= set(manifest["files"])
    with pytest.raises(Exception, match="asset_unavailable"):
        export_godot(referencing(), tmp_path / "unattached")


def test_wheels_bundle_every_runtime_template_file():
    with (ROOT / "pyproject.toml").open("rb") as stream:
        wheel = tomllib.load(stream)["tool"]["hatch"]["build"]["targets"]["wheel"]
    include = wheel["force-include"]
    bundled = {
        source.removeprefix("runtimes/godot/")
        for source, target in include.items()
        if target.startswith("flint_graph/narrative/export/template/")
    }
    assert bundled == set(TEMPLATE_FILES)


def test_runtime_version_is_pinned_consistently():
    toolchain = json.loads((ROOT / "runtimes/godot/toolchain.json").read_bytes())
    assert toolchain["runtime_version"] == "0.7.0"
    assert BuildIdentity("sha256:" + "a" * 64, "b" * 64).runtime_version == "0.7.0"
    assert "runtime 0.7.0" in (ROOT / "runtimes/godot/README.txt").read_text()


def child_fixture(tmp_path):
    source = tmp_path / "input"
    export_godot(attach_assets(referencing(), BYTES), source)
    trusted = {name: sha((source / name).read_bytes()) for name in TEMPLATE_FILES}
    engine = tmp_path / "fixture_engine.py"
    engine.write_text(
        "import pathlib, sys\n"
        "if '--export-release' in sys.argv:\n"
        "    root = pathlib.Path(sys.argv[-1]).parent\n"
        "    for name in ['index.html','index.js','index.wasm','index.pck','index.png',\n"
        "                 'index.audio.worklet.js','index.audio.position.worklet.js']:\n"
        "        (root / name).write_bytes(b'fixture')\n",
        encoding="utf-8",
    )
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    return source, scratch, trusted, (sys.executable, str(engine))


def rewrite(source, name, data):
    (source / name).write_bytes(data)
    path = source / "build-manifest.json"
    manifest = json.loads(path.read_bytes())
    manifest["files"][name] = sha(data)
    path.write_text(json.dumps(manifest), encoding="utf-8")


def test_child_copies_exactly_the_package_assets_into_the_project(tmp_path):
    source, scratch, trusted, command = child_fixture(tmp_path)
    outcome = run_build(source, scratch, trusted, engine_command=command)
    assert outcome["status"] == "ready"
    project = scratch / "project"
    assert (project / "content/assets/dusk.png").read_bytes() == DUSK
    assert (project / "content/assets/type.ttf.import").exists()
    assert (project / "content/assets/hi.wav").read_bytes() == HI
    assert (project / "content/assets/hi.wav.import").exists()


@pytest.mark.parametrize(
    "tamper",
    [
        # A different remap could import the asset as something else entirely.
        lambda s: rewrite(s, "content/assets/dusk.png.import", b'[remap]\nimporter="image"\n'),
        # Bytes that are not the package's asset, even with a matching build manifest.
        lambda s: rewrite(s, "content/assets/dusk.png", MIRA),
        # A file the package does not list.
        lambda s: (
            rewrite(s, "content/assets/extra.png", DUSK),
            rewrite(
                s,
                "content/assets/extra.png.import",
                b'[remap]\nimporter="keep"\n\n[deps]\nsource_file="res://content/assets/'
                b'extra.png"\n\n[params]\n',
            ),
        ),
        # An asset without its remap.
        lambda s: rewrite(s, "content/assets/odd.png", DUSK),
        # Oversized font.
        lambda s: rewrite(s, "content/assets/type.ttf", b"\0" * (8 * MIB + 1)),
    ],
)
def test_child_refuses_assets_that_do_not_match_the_package(tmp_path, tamper):
    source, scratch, trusted, command = child_fixture(tmp_path)
    tamper(source)
    outcome = run_build(source, scratch, trusted, engine_command=command)
    assert outcome == {"schema_version": "1", "status": "failed", "code": "input_integrity"}
    assert not (scratch / "project").exists()


def test_child_refuses_the_previous_runtime_version(tmp_path):
    source, scratch, trusted, command = child_fixture(tmp_path)
    path = source / "build-manifest.json"
    manifest = json.loads(path.read_bytes())
    manifest["runtime_version"] = "0.5.0"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert run_build(source, scratch, trusted, engine_command=command)["code"] == "input_integrity"


def test_child_output_bounds_fit_a_full_asset_budget_beside_the_engine(tmp_path):
    source, scratch, trusted, command = child_fixture(tmp_path)
    (tmp_path / "fixture_engine.py").write_text(
        "import pathlib, sys\n"
        "if '--export-release' in sys.argv:\n"
        "    root = pathlib.Path(sys.argv[-1]).parent\n"
        "    for name in ['index.html','index.js','index.png',\n"
        "                 'index.audio.worklet.js','index.audio.position.worklet.js']:\n"
        "        (root / name).write_bytes(b'fixture')\n"
        "    (root / 'index.wasm').write_bytes(b'w' * (38 * 1024 * 1024))\n"
        "    (root / 'index.pck').write_bytes(b'p' * (55 * 1024 * 1024))\n",
        encoding="utf-8",
    )
    outcome = run_build(source, scratch, trusted, engine_command=command)
    assert outcome["status"] == "ready"
    assert outcome["files"]["index.pck"]["bytes"] == 55 * MIB


def test_raised_transfer_limits_still_have_hard_ceilings():
    assert ArtifactLimits().total_bytes == 96 * MIB and ArtifactLimits().file_bytes == 64 * MIB
    for field, value in [
        ("wire_bytes", 100 * MIB + 1),
        ("file_bytes", 64 * MIB + 1),
        ("total_bytes", 96 * MIB + 1),
        ("max_files", 1025),
    ]:
        with pytest.raises(ValueError):
            ArtifactLimits(**{field: value})
    files = {f"content/assets/a{index}.png": b"x" for index in range(40)}
    with pytest.raises(ArtifactError, match="invalid_zip_inventory"):
        make_artifact_zip(files)
    assert make_artifact_zip(files, limits=SOURCE_LIMITS).startswith(b"PK")


def test_web_zip_with_a_full_asset_budget_stays_under_the_publication_cap():
    # Assets are incompressible PNG data. The pinned 37.7 MiB engine deflates to about
    # 9.9 MiB (measured release web ZIP, 2026-10-30); model it as 10 MiB of noise.
    pack = os.urandom(48 * MIB)
    engine = os.urandom(10 * MIB) + bytes(28 * MIB)
    archive = make_artifact_zip({"index.pck": pack, "index.wasm": engine})
    assert len(archive) <= 64 * MIB
    with zipfile.ZipFile(io.BytesIO(archive)) as opened:
        assert opened.read("index.pck") == pack


async def current():
    pass


@pytest.mark.anyio
async def test_builder_ships_assets_in_the_source_and_refuses_missing_bytes(tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    script = Path(__file__).parents[1] / "fixtures/narrative/owned_docker_cli.py"
    runner = DockerNarrativeBuilder(
        image="sha256:" + "a" * 64,
        toolchain_sha256="b" * 64,
        work_root=scratch,
        docker_command=(sys.executable, str(script), str(tmp_path), "normal"),
    )
    with pytest.raises(BuildError, match=r"^input_integrity$"):
        await runner.build(referencing(), execution_id=uuid4(), check=current)
    built = await runner.build(
        attach_assets(referencing(), BYTES), execution_id=uuid4(), check=current
    )
    with zipfile.ZipFile(io.BytesIO(built.source_zip)) as source:
        assert source.read("content/assets/type.ttf") == TYPE
        assert "content/assets/dusk.png.import" in source.namelist()
    with zipfile.ZipFile(io.BytesIO(built.web_zip)) as web:
        assert web.read("NOTICES.txt") == b"Notices.\n"
    assert json.loads((tmp_path / "created-tmpfs.json").read_text())["/tmp"] == (
        "rw,size=100663296,mode=1777"
    )
    assert list(scratch.iterdir()) == []

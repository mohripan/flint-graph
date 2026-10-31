"""Export a validated immutable snapshot as fresh editable Godot source."""

import hashlib
import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from flint_graph.narrative.values import StoryPackage, canonical_json

TEMPLATE_FILES = (
    "project.godot",
    "main.tscn",
    "runtime/bootstrap.gd",
    "runtime/strict_json.gd",
    "runtime/player.gd",
    "runtime/game_view.gd",
    "runtime/vn_view.gd",
    "runtime/save_store.gd",
    "fonts/Lora.ttf",
    "fonts/LICENSE-Lora.txt",
    "fonts/provenance.json",
    "export_presets.cfg",
    "LICENSE.runtime.txt",
    "GODOT-NOTICE.txt",
    "README.txt",
    "toolchain.json",
)


class ExportError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ExportResult:
    package_hash: str
    manifest_hash: str
    file_count: int
    godot_version: str


def _templates() -> dict[str, bytes]:
    bundled = files("flint_graph.narrative.export").joinpath("template")
    if bundled.is_dir():
        return {name: bundled.joinpath(name).read_bytes() for name in TEMPLATE_FILES}
    # Editable source checkout; wheels carry the same files via Hatch force-include.
    checkout = Path(__file__).resolve().parents[4]
    if not (checkout / "pyproject.toml").is_file():
        raise ExportError("runtime_unavailable")
    return {name: (checkout / "runtimes/godot" / name).read_bytes() for name in TEMPLATE_FILES}


def export_godot(package: StoryPackage, target: Path) -> ExportResult:
    try:
        payloads = _templates()
    except OSError:
        raise ExportError("runtime_unavailable") from None
    toolchain = json.loads(payloads["toolchain.json"])
    payloads["content/story.json"] = package.canonical_story
    payloads["content/NOTICES.txt"] = package.notices
    payloads["content/package-manifest.json"] = canonical_json(package.manifest)
    for asset in package.assets:
        if asset.data is None:
            # A Studio reference whose verified bytes were never loaded cannot ship.
            raise ExportError("asset_unavailable")
        payloads["content/" + asset.path] = asset.data
        # Keep exact validated PNG and font bytes available to FileAccess in exported PCKs.
        payloads["content/" + asset.path + ".import"] = (
            '[remap]\nimporter="keep"\n\n[deps]\nsource_file="res://content/'
            + asset.path
            + '"\n\n[params]\n'
        ).encode()
    manifest = canonical_json(
        {
            "schema_version": "1",
            "package_hash": package.content_hash,
            "compiler_version": "0.1.0",
            "runtime_version": toolchain["runtime_version"],
            "godot_version": toolchain["godot_version"],
            "files": {
                name: hashlib.sha256(data).hexdigest() for name, data in sorted(payloads.items())
            },
        }
    )
    payloads["build-manifest.json"] = manifest
    created = False
    try:
        absolute = target.absolute()
        parent = absolute.parent
        if parent.resolve(strict=True) != parent:
            raise ExportError("unsafe_output_path")
        if target.exists() or target.is_symlink():
            raise ExportError("output_exists")
        target.mkdir()  # Exclusive reservation; never replace even an empty directory.
        created = True
        # Write the readiness manifest last; preserve failed new output for inspection.
        order = sorted(name for name in payloads if name != "build-manifest.json")
        for name in [*order, "build-manifest.json"]:
            data = payloads[name]
            destination = target / name
            for directory in reversed(destination.parent.parents):
                if directory == target or target not in directory.parents:
                    continue
                if not directory.exists():
                    directory.mkdir()
            if destination.parent != target and not destination.parent.exists():
                destination.parent.mkdir()
            with destination.open("xb") as stream:
                stream.write(data)
        return ExportResult(
            package.content_hash,
            hashlib.sha256(manifest).hexdigest(),
            len(payloads),
            toolchain["godot_version"],
        )
    except ExportError:
        raise
    except FileExistsError:
        raise ExportError("incomplete_export" if created else "output_exists") from None
    except OSError:
        raise ExportError("incomplete_export" if created else "export_io") from None

"""Build the trusted, source-free studio preview with the explicitly pinned toolchain."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
WINDOWS_ENGINE = "Godot_v4.7.2-stable_win64.exe"
LINUX_ENGINE = "Godot_v4.7.2-stable_linux.x86_64"
# The origin goes into a security header and a script, so only these characters may reach them.
HOST = re.compile(r"[A-Za-z0-9.-]+\Z")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_parent(value: str) -> str:
    """The one editor that may embed this build: on this computer, or a site served over HTTPS."""
    parsed = urlsplit(value)
    local = parsed.scheme == "http" and parsed.hostname == "localhost" and bool(parsed.port)
    if (
        not (local or parsed.scheme == "https")
        or not HOST.match(parsed.hostname or "")
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "The editor's origin must be http://localhost:<port> or https://<host>, "
            "without path or credentials"
        )
    return value


def pinned_engine(name: str) -> str:
    if name == WINDOWS_ENGINE:
        return str(
            json.loads((ROOT / "runtimes/godot/toolchain.json").read_bytes())["extracted_sha256"][
                name
            ]
        )
    if name == LINUX_ENGINE:
        return str(
            json.loads((ROOT / "ops/narrative/toolchain-linux.json").read_bytes())["engine_sha256"]
        )
    raise ValueError("Unqualified toolchain: " + name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--templates", type=Path, required=True)
    parser.add_argument("--parent-origin", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    parent = checked_parent(args.parent_origin)
    engine, templates = args.engine.resolve(strict=True), args.templates.resolve(strict=True)
    runtime = ROOT / "runtimes/godot"
    pin = json.loads((runtime / "toolchain.json").read_bytes())
    if digest(engine) != pinned_engine(engine.name):
        raise ValueError("Unqualified toolchain: " + engine.name)
    for mode in ["debug", "release"]:
        name = f"web_nothreads_{mode}.zip"
        if digest(templates / name) != pin["extracted_sha256"][name]:
            raise ValueError("Unqualified toolchain: " + name)
    output = args.output.absolute()
    if (
        output.exists()
        or output.is_symlink()
        or output.parent.resolve(strict=True) != output.parent
    ):
        raise ValueError("Output must be a new directory under a real parent")
    output.mkdir()
    project, web = output / "project", output / "web"
    project.mkdir()
    web.mkdir()
    names = [
        "project.godot",
        "main.tscn",
        "export_presets.cfg",
        "LICENSE.runtime.txt",
        "GODOT-NOTICE.txt",
        "runtime/player.gd",
        "runtime/game_view.gd",
        "runtime/vn_view.gd",
        "runtime/save_store.gd",
        "runtime/player_terms.gd",
        "runtime/reading.gd",
        "runtime/sound_channel.gd",
        "runtime/strict_json.gd",
        "fonts/Lora.ttf",
        "fonts/LICENSE-Lora.txt",
        "fonts/provenance.json",
        "preview/bootstrap.gd",
        "preview/game_view.gd",
        "preview/vn_view.gd",
        "preview/validate_story.gd",
        "preview/shell.html",
    ]
    for name in names:
        target = project / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(runtime / name, target)
    scene = project / "main.tscn"
    scene.write_text(
        scene.read_text().replace("res://runtime/bootstrap.gd", "res://preview/bootstrap.gd"),
        encoding="utf-8",
        newline="\n",
    )
    presets = project / "export_presets.cfg"
    text = presets.read_text().replace(
        "html/export_icon=false",
        'html/export_icon=false\nhtml/custom_html_shell="res://preview/shell.html"',
    )
    for mode in ["debug", "release"]:
        text = text.replace(
            f'custom_template/{mode}=""',
            f'custom_template/{mode}="{(templates / f"web_nothreads_{mode}.zip").as_posix()}"',
        )
    presets.write_text(text, encoding="utf-8", newline="\n")
    environment = os.environ.copy()
    for key in [
        "APPDATA",
        "LOCALAPPDATA",
        "TEMP",
        "TMP",
        "HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
    ]:
        folder = output / "profile" / key
        folder.mkdir(parents=True)
        environment[key] = str(folder)
    for name, arguments in [
        ("import", ["--editor", "--import"]),
        ("web", ["--export-release", "Web", str(web / "index.html")]),
    ]:
        result = subprocess.run(
            [str(engine), "--headless", "--path", str(project), *arguments],
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
        (output / f"{name}.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        if result.returncode or "SCRIPT ERROR" in result.stderr or "Parse Error" in result.stderr:
            raise RuntimeError("Engine failed; inspect retained " + name + ".log")
    (web / "bridge.js").write_text(
        (runtime / "preview/bridge.js")
        .read_text()
        .replace("__TRUSTED_PARENT_ORIGIN__", json.dumps(parent)),
        encoding="utf-8",
        newline="\n",
    )
    shutil.copyfile(runtime / "preview/preview.css", web / "preview.css")
    for name in [
        "LICENSE.runtime.txt",
        "GODOT-NOTICE.txt",
        "fonts/LICENSE-Lora.txt",
        "fonts/provenance.json",
    ]:
        shutil.copyfile(runtime / name, web / Path(name).name)
    report = {
        "schema_version": "1",
        "parent_origin": parent,
        "engine": pin["godot_version"],
        "runtime": pin["runtime_version"],
        "source_files": {name: digest(project / name) for name in names},
        "files": {p.name: digest(p) for p in sorted(web.iterdir()) if p.is_file()},
        "browser_qualified": False,
    }
    (output / "preview-build.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print("Trusted preview built at " + str(web) + "; browser qualification remains required")


if __name__ == "__main__":
    main()

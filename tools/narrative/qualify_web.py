"""Explicit local qualification builds of the original sample and long-text case.

No downloads, global installation, existing-directory overwrite or server startup.
This is a development proof helper, not a hosted creator-code build service.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

from flint_graph.narrative import load_package
from flint_graph.narrative.export import export_godot

ROOT = Path(__file__).resolve().parents[2]


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", required=True, type=Path)
    parser.add_argument("--templates", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    engine = args.engine.resolve(strict=True)
    templates = args.templates.resolve(strict=True)
    pin = json.loads((ROOT / "runtimes/godot/toolchain.json").read_bytes())
    if digest(engine) != pin["extracted_sha256"]["Godot_v4.7.2-stable_win64.exe"]:
        parser.error("unqualified engine executable")
    for mode in ["debug", "release"]:
        name = f"web_nothreads_{mode}.zip"
        if digest(templates / name) != pin["extracted_sha256"][name]:
            parser.error("unqualified template: " + name)
    target = args.output.absolute()
    if target.exists() or target.is_symlink():
        parser.error("output must be a new directory")
    if target.parent.resolve(strict=True) != target.parent:
        parser.error("output parent must not be a symlink/junction alias")
    target.mkdir()
    environment = os.environ.copy()
    for key, name in [
        ("APPDATA", "Roaming"),
        ("LOCALAPPDATA", "Local"),
        ("TEMP", "Temp"),
        ("TMP", "Temp"),
    ]:
        folder = target / "profile" / name
        folder.mkdir(parents=True, exist_ok=True)
        environment[key] = str(folder)

    def run(project: Path, name: str, *arguments: str) -> str:
        result = subprocess.run(
            [str(engine), "--headless", "--path", str(project), *arguments],
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
            check=False,
        )
        (target / (name + ".log")).write_text(result.stdout + result.stderr, encoding="utf-8")
        if result.returncode or "SCRIPT ERROR" in result.stderr or "Parse Error" in result.stderr:
            raise RuntimeError("engine failed: " + name + "; inspect retained logs")
        return result.stdout

    fixture = ROOT / "tests/fixtures/narrative/lantern_archive"
    long_source = target / "long-source"
    shutil.copytree(fixture, long_source)
    story = json.loads((long_source / "story.json").read_bytes())
    story["nodes"]["arrival"]["text"] = "\n\n".join(
        f"Passage {index + 1}. The lantern casts a small circle across the archive desk. "
        "We read slowly, checking each page before turning to the next."
        for index in range(70)
    )
    (long_source / "story.json").write_text(json.dumps(story), encoding="utf-8")
    results = {}
    public = target / "web"
    public.mkdir()
    for name, source in [("sample", fixture), ("long", long_source)]:
        package = load_package(source)
        project = target / (name + "-project")
        export = export_godot(package, project)
        presets = project / "export_presets.cfg"
        text = presets.read_text(encoding="utf-8")
        for mode in ["debug", "release"]:
            template = (templates / f"web_nothreads_{mode}.zip").as_posix()
            text = text.replace(
                f'custom_template/{mode}=""', f'custom_template/{mode}="{template}"'
            )
        presets.write_text(text, encoding="utf-8", newline="\n")
        run(project, name + "-import", "--editor", "--import")
        verified = run(project, name + "-content", "--", "--verify-content")
        if "CONTENT_OK:" + package.content_hash not in verified:
            raise RuntimeError("missing content verification marker: " + name)
        web = public / name
        web.mkdir()
        run(project, name + "-web", "--export-release", "Web", str(web / "index.html"))
        for suffix in ["html", "js", "wasm", "pck"]:
            if not (web / ("index." + suffix)).is_file():
                raise RuntimeError("missing Web output: " + suffix)
        results[name] = {
            "package_hash": package.content_hash,
            "source_manifest_hash": export.manifest_hash,
            "files": {p.name: digest(p) for p in sorted(web.iterdir())},
        }
    report = {
        "qualified_engine": pin["godot_version"],
        "runtime": pin["runtime_version"],
        "builds": results,
        "serve_only": str(public),
        "browser_qualified": False,
    }
    (target / "build-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

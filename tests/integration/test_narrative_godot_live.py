"""Opt-in native qualification using a verified task-local official Godot binary."""

import base64
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from flint_graph.narrative import Player, StoryPackage, load_package
from flint_graph.narrative.export import export_godot

ENGINE = os.environ.get("FLINT_GRAPH_NARRATIVE_GODOT_BIN")
pytestmark = pytest.mark.skipif(
    not ENGINE, reason="Set FLINT_GRAPH_NARRATIVE_GODOT_BIN for real engine checks"
)
FIXTURE = Path(__file__).parents[1] / "fixtures/narrative/lantern_archive"


def native_environment(root: Path) -> dict[str, str]:
    environment = os.environ.copy()
    for key, name in [
        ("APPDATA", "Roaming"),
        ("LOCALAPPDATA", "Local"),
        ("TEMP", "Temp"),
        ("TMP", "Temp"),
    ]:
        path = root / "profile" / name
        path.mkdir(parents=True, exist_ok=True)
        environment[key] = str(path)
    return environment


def run_engine(
    project: Path, environment: dict[str, str], *args: str
) -> subprocess.CompletedProcess[str]:
    assert ENGINE
    with Path(ENGINE).open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == (
            "ab1824f85bfd8e0e4128182c000c4003a3e042245b2967848d089b2a04b22424"
        )
    return subprocess.run(
        [ENGINE, "--headless", "--path", str(project), *args],
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
        check=False,
    )


def test_real_pinned_engine_imports_and_checks_the_exported_content(tmp_path: Path) -> None:
    assert ENGINE
    with Path(ENGINE).open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    toolchain = json.loads(
        (Path(__file__).parents[2] / "runtimes/godot/toolchain.json").read_bytes()
    )
    assert digest == toolchain["extracted_sha256"]["Godot_v4.7.2-stable_win64.exe"]
    project = tmp_path / "game"
    package = load_package(FIXTURE)
    export_godot(package, project)
    environment = native_environment(tmp_path)
    imported = run_engine(project, environment, "--editor", "--import")
    assert imported.returncode == 0, imported.stderr
    assert "SCRIPT ERROR" not in imported.stderr

    checked = run_engine(project, environment, "--", "--verify-content")

    assert checked.returncode == 0, checked.stderr
    assert f"CONTENT_OK:{package.content_hash}" in checked.stdout
    (project / "content/assets/archive.png").write_bytes(b"tampered source image")
    rejected = run_engine(project, environment, "--", "--verify-content")
    assert rejected.returncode != 0
    assert "asset_hash_mismatch" in rejected.stderr


ROUTES = json.loads((FIXTURE.parent / "lantern_routes.json").read_bytes())["routes"]


def native_probe(package: StoryPackage, tmp_path: Path, configuration: dict) -> dict:
    project = tmp_path / "game"
    export_godot(package, project)
    (project / "qualification.gd").write_bytes((FIXTURE.parent / "godot_probe.gd").read_bytes())
    (project / "qualification.json").write_text(json.dumps(configuration), encoding="utf-8")
    environment = native_environment(tmp_path)
    imported = run_engine(project, environment, "--editor", "--import")
    assert imported.returncode == 0, imported.stderr
    result = run_engine(
        project, environment, "--script", "res://qualification.gd", "--quit-after", "2"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SCRIPT ERROR" not in result.stderr
    raw = next(
        line.removeprefix("PROBE_RESULT:")
        for line in result.stdout.splitlines()
        if line.startswith("PROBE_RESULT:")
    )
    return json.loads(raw)


@pytest.mark.parametrize("route", ROUTES, ids=[item["id"] for item in ROUTES])
def test_real_godot_player_matches_reference_routes_and_saves(tmp_path: Path, route: dict) -> None:
    package = load_package(FIXTURE)
    actual = native_probe(package, tmp_path, {"actions": route["actions"], "save_after": 1})
    reference = Player(package)
    frames = [reference.frame()]
    for action in route["actions"]:
        reference.act(action)
        frames.append(reference.frame(action))

    assert actual["frames"] == frames
    assert actual["state"] == reference.state
    assert actual["restore_error"] == ""
    restored = Player(package)
    restored.load_save(actual["save"].encode())
    assert restored.state["node_id"] == "approach_choice"


def test_native_strict_json_rejects_permissive_syntax_and_preserves_valid_values(
    tmp_path: Path,
) -> None:
    valid = [
        b'{"value":-2147483648}',
        b'{"value":2147483647}',
        b'{"value":"\\ud83d\\ude82"}',
        '{"value":"朝"}'.encode(),
        b"[" * 64 + b"]" * 64,
    ]
    invalid = [
        b'{"x":1,"\\u0078":2}',
        b'{"x":1,}',
        b"[1,]",
        b'{"x":"\n"}',
        b"\xef\xbb\xbf{}",
        b'{"x":"\xff"}',
        b'{"x":"\\ud800"}',
        b'{"x":"\\udc00"}',
        b'{"x":"\\ud800\\u0041"}',
        b'{"x":"\\u0000"}',
        b'{"x":2147483648}',
        b'{"x":-2147483649}',
        b'{"x":1.0}',
        b'{"x":1e0}',
        b'{"x":01}',
        b'{"x":NaN}',
        b"[" * 65 + b"]" * 65,
    ]
    encoded = [base64.b64encode(value).decode() for value in valid + invalid]

    actual = native_probe(load_package(FIXTURE), tmp_path, {"decode_inputs": encoded})["decoded"]

    assert [item["ok"] for item in actual] == [True] * len(valid) + [False] * len(invalid)
    assert [item["value"] for item in actual[: len(valid)]] == [
        json.loads(value) for value in valid
    ]


def test_native_bad_saves_preserve_state_and_callback_generation(tmp_path: Path) -> None:
    package = load_package(FIXTURE)
    original = Player(package).save()
    wrong_hash = json.loads(original)
    wrong_hash["package_hash"] = "0" * 64
    wrong_node = json.loads(original)
    wrong_node["node_id"] = "earn_trust"
    wrong_ending = json.loads(original)
    wrong_ending["ending"] = "restored"
    invalid = [
        original[:-1] + b",}",
        original.replace(b'"trust":0', b'"trust":true'),
        original.replace(b'"trust":0', b'"trust":0.0'),
        b"null",
        b"[]",
        b'{"x":"\\ud800"}',
        b'{"x":"\xff"}',
        json.dumps(wrong_hash).encode(),
        json.dumps(wrong_node).encode(),
        json.dumps(wrong_ending).encode(),
    ]
    encoded = [base64.b64encode(value).decode() for value in [original, *invalid]]

    actual = native_probe(package, tmp_path, {"restore_cases": encoded})["restored"]

    assert actual[0] == {"error": "", "preserved": True, "generation_change": 1}
    assert actual[1:] == [
        {"error": "invalid_save", "preserved": True, "generation_change": 0}
    ] * len(invalid)


def test_native_invalid_and_stale_actions_do_not_change_state(tmp_path: Path) -> None:
    cases = [
        {"setup": [], "action": None},
        {"setup": [], "action": 1},
        {"setup": [], "action": "choose:listen"},
        {"setup": [], "action": "advance", "generation": True},
        {"setup": [], "action": "advance", "generation": -1},
        {"setup": ["advance"], "action": "advance"},
        {"setup": ["advance"], "action": "choose:missing"},
        {"setup": ["advance"], "action": "choose:listen", "generation": 0},
        {"setup": ["advance", "choose:leave"], "action": "advance"},
    ]

    actual = native_probe(load_package(FIXTURE), tmp_path, {"action_cases": cases})["actions"]

    assert actual == [{"error": "invalid_action", "preserved": True}] * len(cases)


def state_package(tmp_path: Path, nodes: dict, variables: dict) -> StoryPackage:
    source = tmp_path / "source"
    source.mkdir()
    story = {
        "schema_version": "1",
        "id": "native_state",
        "title": "Original state fixture",
        "language": "en",
        "entry": "start",
        "characters": {},
        "assets": {},
        "variables": variables,
        "nodes": {
            "finish": {"type": "end", "text_id": "end_text", "text": "End.", "ending": "done"},
            **nodes,
        },
    }
    (source / "story.json").write_text(json.dumps(story), encoding="utf-8")
    (source / "NOTICES.txt").write_text("Original native state regression.\n", encoding="utf-8")
    return load_package(source)


@pytest.mark.parametrize("case", ["positive_overflow", "negative_overflow", "loop", "no_choices"])
def test_native_fault_states_and_saves_match_reference(tmp_path: Path, case: str) -> None:
    initial = (
        2147483647
        if case == "positive_overflow"
        else (-2147483648 if case == "negative_overflow" else 0)
    )
    variables = {
        "count": {"type": "int", "initial": initial},
        "known": {"type": "bool", "initial": False},
    }
    if case == "no_choices":
        nodes = {
            "start": {
                "type": "choice",
                "text_id": "choice_text",
                "text": "Locked.",
                "options": [
                    {
                        "id": "locked",
                        "text_id": "locked_text",
                        "text": "Locked",
                        "target": "finish",
                        "condition": {"op": "eq", "variable": "known", "value": True},
                    }
                ],
            }
        }
    else:
        nodes = {
            "start": {
                "type": "set",
                "next": "start" if case == "loop" else "finish",
                "operations": [
                    {"op": "set", "variable": "known", "value": True},
                    {
                        "op": "increment",
                        "variable": "count",
                        "value": -1 if case == "negative_overflow" else 1,
                    },
                ],
            }
        }
    package = state_package(tmp_path, nodes, variables)

    actual = native_probe(package, tmp_path, {"save_initial": True})

    assert actual["state"] == Player(package).state
    assert actual["restore_error"] == ""
    restored = Player(package)
    restored.load_save(actual["save"].encode())
    assert restored.state == actual["state"]


def test_native_large_valid_save_roundtrips_beyond_one_megabyte(tmp_path: Path) -> None:
    variables = {
        f"label_{index}": {"type": "enum", "values": ["x" * 16384], "initial": "x" * 16384}
        for index in range(80)
    }
    package = state_package(
        tmp_path,
        {
            "start": {
                "type": "line",
                "text_id": "start_text",
                "text": "Large valid state.",
                "next": "finish",
            }
        },
        variables,
    )

    actual = native_probe(package, tmp_path, {"save_initial": True})

    assert len(actual["save"]) > 1024 * 1024
    assert actual["restore_error"] == ""
    assert actual["state"] == Player(package).state
    restored = Player(package)
    restored.load_save(actual["save"].encode())
    assert restored.state == actual["state"]


def native_ui_probe(tmp_path: Path, case: str) -> dict:
    project = tmp_path / "game"
    export_godot(load_package(FIXTURE), project)
    (project / "qualification.gd").write_bytes((FIXTURE.parent / "godot_ui_probe.gd").read_bytes())
    (project / "qualification.json").write_text(json.dumps({"case": case}), encoding="utf-8")
    environment = native_environment(tmp_path)
    imported = run_engine(project, environment, "--editor", "--import")
    assert imported.returncode == 0, imported.stderr
    result = run_engine(
        project, environment, "--script", "res://qualification.gd", "--quit-after", "8"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SCRIPT ERROR" not in result.stderr
    return json.loads(
        next(
            line.removeprefix("UI_RESULT:")
            for line in result.stdout.splitlines()
            if line.startswith("UI_RESULT:")
        )
    )


def test_native_ui_rejects_queued_callbacks_from_before_restart(tmp_path: Path) -> None:
    assert native_ui_probe(tmp_path, "stale_restart")["preserved"] is True


def test_native_save_io_failures_preserve_the_previous_good_save(tmp_path: Path) -> None:
    result = native_ui_probe(tmp_path, "save_store")

    assert result["first"] == ""
    assert all(item["error"] and item["preserved"] for item in result["failures"])
    assert result["second"] == ""
    assert result["updated"] is True


@pytest.mark.skipif(
    not os.environ.get("FLINT_GRAPH_NARRATIVE_GODOT_TEMPLATES"),
    reason="Set FLINT_GRAPH_NARRATIVE_GODOT_TEMPLATES for actual Web PCK checks",
)
def test_real_web_pck_retains_content_and_distribution_notices(tmp_path: Path) -> None:
    project = tmp_path / "game"
    export_godot(load_package(FIXTURE), project)
    templates = Path(os.environ["FLINT_GRAPH_NARRATIVE_GODOT_TEMPLATES"])
    toolchain = json.loads((project / "toolchain.json").read_bytes())
    presets = project / "export_presets.cfg"
    text = presets.read_text(encoding="utf-8")
    for mode in ["debug", "release"]:
        template = templates / f"web_nothreads_{mode}.zip"
        with template.open("rb") as stream:
            assert (
                hashlib.file_digest(stream, "sha256").hexdigest()
                == (toolchain["extracted_sha256"][template.name])
            )
        text = text.replace(
            f'custom_template/{mode}=""',
            f'custom_template/{mode}="{template.resolve().as_posix()}"',
        )
    presets.write_text(text, encoding="utf-8")
    environment = native_environment(tmp_path)
    imported = run_engine(project, environment, "--editor", "--import")
    assert imported.returncode == 0 and "SCRIPT ERROR" not in imported.stderr
    web = tmp_path / "web"
    web.mkdir()
    built = run_engine(project, environment, "--export-release", "Web", str(web / "index.html"))
    assert built.returncode == 0, built.stdout + built.stderr
    assert "SCRIPT ERROR" not in built.stderr
    assert all((web / f"index.{suffix}").is_file() for suffix in ["html", "js", "wasm", "pck"])
    # No loose source directory is visible at res://: bytes must come from the PCK.
    probe_root = tmp_path / "pack-probe"
    probe_root.mkdir()
    (probe_root / "probe.gd").write_bytes((FIXTURE.parent / "godot_pack_probe.gd").read_bytes())
    checked = run_engine(
        probe_root,
        environment,
        "--script",
        "res://probe.gd",
        "--quit-after",
        "2",
        "--",
        str(web / "index.pck"),
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert "SCRIPT ERROR" not in checked.stderr
    actual = json.loads(
        next(
            line.removeprefix("PACK_RESULT:")
            for line in checked.stdout.splitlines()
            if line.startswith("PACK_RESULT:")
        )
    )
    assert set(actual) == {
        "fonts/LICENSE-Lora.txt",
        "fonts/provenance.json",
        "content/story.json",
        "content/NOTICES.txt",
        "LICENSE.runtime.txt",
        "GODOT-NOTICE.txt",
    }
    assert actual == {
        path: hashlib.sha256((project / path).read_bytes()).hexdigest() for path in actual
    }

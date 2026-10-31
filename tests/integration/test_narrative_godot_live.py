"""Opt-in native qualification using a verified task-local official Godot binary."""

import base64
import hashlib
import json
import os
import struct
import subprocess
import zlib
from pathlib import Path

import pytest

from flint_graph.narrative import Player, StoryPackage, load_package
from flint_graph.narrative.export import export_godot
from flint_graph.narrative.player import PlayerError

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


def stage_png(red: int, width: int = 6, height: int = 4) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload))
        )

    row = b"\x00" + bytes([red, 80, 40, 255]) * width
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )


def static_font() -> bytes:
    tables = {tag: b"x" * 8 for tag in (b"cmap", b"glyf", b"head", b"loca", b"name")}
    tables[b"OS/2"] = b"\x00" * 16
    header = b"\x00\x01\x00\x00" + struct.pack(">HHHH", len(tables), 16, 4, 0)
    offset, directory, body = 12 + 16 * len(tables), b"", b""
    for tag in sorted(tables):
        directory += tag + struct.pack(">III", 0, offset + len(body), len(tables[tag]))
        body += tables[tag]
    return header + directory + body


def stage_package(
    tmp_path: Path, nodes: dict | None = None, entry: str = "s0", framed: bool = False
) -> StoryPackage:
    """Story format 2 with every stage rule: set, clear, move, replace, hide, expressions."""
    files = {
        "dusk": stage_png(10),
        "pier": stage_png(30, 8, 4),
        "mira_neutral": stage_png(50, 3, 6),
        "mira_happy": stage_png(70, 3, 6),
        "oren_neutral": stage_png(90, 3, 6),
    }
    assets = {
        key: {
            "kind": "image",
            "path": f"assets/{key}.png",
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        for key, data in files.items()
    }
    font = static_font()
    assets["type"] = {
        "kind": "font",
        "path": "assets/type.ttf",
        "sha256": hashlib.sha256(font).hexdigest(),
    }

    def line(key, text, target, **extra):
        return {"type": "line", "text_id": key, "text": text, "next": target, **extra}

    story = {
        "schema_version": "2",
        "id": "harbor_stage",
        "title": "Original stage fixture",
        "language": "en",
        "entry": entry,
        "characters": {
            "mira": {
                "name": "Mira",
                "color": "#d5ae68",
                "sprites": {"neutral": "mira_neutral", "happy": "mira_happy"},
            },
            "oren": {"name": "Oren", "sprites": {"neutral": "oren_neutral"}},
        },
        "variables": {"stayed": {"type": "bool", "initial": False}},
        "assets": assets,
        "theme": {"textbox": {"position": "bottom"}, "font": {"asset": "type", "size": 24}},
        "nodes": nodes
        or {
            "s0": {
                "type": "stage",
                "background": "dusk",
                "show": [{"character": "mira", "sprite": "neutral", "position": "left"}],
                "next": "l1",
            },
            "l1": line("l1", "The bell!", "s1", speaker="mira", expression="happy"),
            "s1": {
                "type": "stage",
                "show": [{"character": "oren", "sprite": "neutral", "position": "center"}],
                "next": "c1",
            },
            "c1": {
                "type": "choice",
                "text_id": "c1",
                "text": "Now?",
                "options": [
                    {"id": "go", "text_id": "go", "text": "Go", "target": "s2"},
                    {"id": "stay", "text_id": "stay", "text": "Stay", "target": "st"},
                ],
            },
            "s2": {
                "type": "stage",
                "background": "pier",
                "hide": ["oren"],
                "show": [{"character": "mira", "sprite": "neutral", "position": "right"}],
                "next": "l2",
            },
            "l2": line("l2", "Wait!", "s3", speaker="oren", expression="neutral"),
            "s3": {
                "type": "stage",
                "show": [{"character": "oren", "sprite": "neutral", "position": "right"}],
                "next": "e1",
            },
            "e1": {"type": "end", "text_id": "e1", "text": "Gone.", "ending": "quiet"},
            "st": {
                "type": "set",
                "operations": [{"op": "set", "variable": "stayed", "value": True}],
                "next": "b1",
            },
            "b1": {
                "type": "branch",
                "condition": {"op": "eq", "variable": "stayed", "value": True},
                "if_true": "s4",
                "if_false": "e1",
            },
            "s4": {"type": "stage", "background": None, "next": "l3"},
            "l3": line("l3", "Dark now.", "e2", speaker="mira"),
            "e2": {"type": "end", "text_id": "e2", "text": "Stayed.", "ending": "dark"},
        },
    }
    if framed:
        # Runtime 0.4.0: Mira drawn at 160% of the screen height from 4% down, at x 30.
        story["characters"]["mira"]["stage"] = {"scale": 160, "top": 4}
        story["nodes"]["s0"]["show"][0]["x"] = 30
    source = tmp_path / "source"
    (source / "assets").mkdir(parents=True)
    (source / "story.json").write_text(json.dumps(story), encoding="utf-8")
    (source / "NOTICES.txt").write_text("Original stage fixture. CC0.\n", encoding="utf-8")
    for key, data in files.items():
        (source / f"assets/{key}.png").write_bytes(data)
    (source / "assets/type.ttf").write_bytes(font)
    return load_package(source)


@pytest.mark.parametrize(
    "actions",
    [["advance", "choose:go", "advance"], ["advance", "choose:stay", "advance"]],
    ids=["moves_and_replaces", "clears_background"],
)
def test_real_godot_player_matches_reference_stage_routes_and_saves(
    tmp_path: Path, actions: list[str]
) -> None:
    package = stage_package(tmp_path)
    actual = native_probe(package, tmp_path, {"actions": actions, "save_after": 1})
    reference = Player(package)
    frames = [reference.frame()]
    for action in actions:
        reference.act(action)
        frames.append(reference.frame(action))

    assert actual["frames"] == frames
    assert actual["state"] == reference.state
    assert actual["restore_error"] == ""
    restored = Player(package)
    restored.load_save(actual["save"].encode())
    assert restored.state["node_id"] == "c1"
    assert restored.state["stage"]["characters"] == [
        {"id": "mira", "sprite": "happy", "position": "left"},
        {"id": "oren", "sprite": "neutral", "position": "center"},
    ]


def test_native_stage_saves_are_validated_like_the_reference(tmp_path: Path) -> None:
    package = stage_package(tmp_path)
    player = Player(package)
    player.act("advance")
    original = player.save()

    def changed(edit) -> bytes:
        value = json.loads(original)
        edit(value)
        return json.dumps(value).encode()

    stage = "stage"
    invalid = [
        changed(lambda s: s.pop(stage)),
        changed(lambda s: s.update(schema_version="1")),
        changed(lambda s: s[stage]["characters"][0].update(sprite="angry")),
        changed(lambda s: s[stage]["characters"][0].update(position="center")),
        changed(lambda s: s[stage]["characters"].reverse()),
        changed(lambda s: s[stage]["characters"].append(dict(s[stage]["characters"][0]))),
        changed(lambda s: s[stage].update(background="type")),
        changed(lambda s: s[stage].update(background="missing")),
        changed(lambda s: s[stage].update(extra=1)),
    ]
    for data in invalid:
        with pytest.raises(PlayerError):
            Player(package).load_save(data)
    encoded = [base64.b64encode(value).decode() for value in [original, *invalid]]

    actual = native_probe(package, tmp_path, {"restore_cases": encoded})["restored"]

    # The valid save is from a later screen, so loading it changes the state.
    assert actual[0] == {"error": "", "preserved": False, "generation_change": 1}
    assert actual[1:] == [
        {"error": "invalid_save", "preserved": True, "generation_change": 0}
    ] * len(invalid)


def test_native_stage_loop_faults_and_saves_like_the_reference(tmp_path: Path) -> None:
    nodes = {
        "s0": {"type": "stage", "background": "dusk", "next": "s0"},
        "e1": {"type": "end", "text_id": "e1", "text": "Never.", "ending": "never"},
    }
    package = stage_package(tmp_path, nodes)

    actual = native_probe(package, tmp_path, {"save_initial": True})

    reference = Player(package)
    assert reference.state["fault"] == "automatic_transition_limit"
    assert actual["state"] == reference.state
    assert actual["restore_error"] == ""
    restored = Player(package)
    restored.load_save(actual["save"].encode())
    assert restored.state == actual["state"]


def test_native_bootstrap_verifies_font_assets(tmp_path: Path) -> None:
    project = tmp_path / "game"
    package = stage_package(tmp_path)
    export_godot(package, project)
    environment = native_environment(tmp_path)
    assert run_engine(project, environment, "--editor", "--import").returncode == 0
    checked = run_engine(project, environment, "--", "--verify-content")
    assert checked.returncode == 0, checked.stderr
    assert f"CONTENT_OK:{package.content_hash}" in checked.stdout
    (project / "content/assets/type.ttf").write_bytes(b"tampered font")
    rejected = run_engine(project, environment, "--", "--verify-content")
    assert rejected.returncode != 0
    assert "asset_hash_mismatch" in rejected.stderr


def native_ui_probe(
    tmp_path: Path, case: str, package: StoryPackage | None = None, extra: dict | None = None
) -> dict:
    project = tmp_path / "game"
    export_godot(package or load_package(FIXTURE), project)
    if case.endswith("_preview"):
        preview = project / "preview"
        preview.mkdir()
        (preview / "vn_view.gd").write_bytes(
            (Path(__file__).parents[2] / "runtimes/godot/preview/vn_view.gd").read_bytes()
        )
    (project / "qualification.gd").write_bytes((FIXTURE.parent / "godot_ui_probe.gd").read_bytes())
    (project / "qualification.json").write_text(
        json.dumps({"case": case, **(extra or {})}), encoding="utf-8"
    )
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


def test_real_godot_player_matches_reference_with_framing_and_placement(tmp_path: Path) -> None:
    package = stage_package(tmp_path, framed=True)
    actions = ["advance", "choose:go", "advance"]
    actual = native_probe(package, tmp_path, {"actions": actions, "save_after": 1})
    reference = Player(package)
    frames = [reference.frame()]
    for action in actions:
        reference.act(action)
        frames.append(reference.frame(action))
    assert actual["frames"] == frames
    assert frames[0]["stage"]["characters"][0]["x"] == 30
    restored = Player(package)
    restored.load_save(actual["save"].encode())
    assert restored.state["stage"]["characters"][0] == {
        "id": "mira",
        "sprite": "happy",
        "position": "left",
        "x": 30,
    }


def test_native_stage_view_draws_framed_figures_cut_off_below(tmp_path: Path) -> None:
    opening = native_ui_probe(tmp_path, "stage_layout", stage_package(tmp_path, framed=True))[
        "screens"
    ][0]
    (mira,) = opening["figures"]
    # 160% of 720 tall from 4% down, keeping the 1:2 sprite aspect, centred at 30%.
    assert mira["height"] == pytest.approx(720 * 1.6, abs=1)
    assert mira["width"] == pytest.approx(720 * 1.6 / 2, abs=1)
    assert mira["bottom"] == pytest.approx(720 * 0.04 + 720 * 1.6, abs=1)
    assert mira["x"] + mira["width"] / 2 == pytest.approx(1280 * 0.3, abs=1)


def test_native_stage_view_lays_out_the_stage_text_box_and_choices(tmp_path: Path) -> None:
    screens = native_ui_probe(tmp_path, "stage_layout", stage_package(tmp_path))["screens"]

    opening, choice, moved, ending = screens
    # The text box sits at the bottom, 92% wide and centred, with the speaker's name.
    assert opening["text"] == "The bell!" and opening["name"] == "Mira"
    box = opening["box"]
    assert box["bottom"] == pytest.approx(720 - 24, abs=1)
    assert box["left"] == pytest.approx(1280 * 0.04, abs=1)
    assert box["right"] == pytest.approx(1280 * 0.96, abs=1)
    assert opening["background"] and opening["buttons"] == ["Continue"]
    # Sprites keep their 1:2 aspect and stand on the bottom edge in their slot.
    (mira,) = opening["figures"]
    assert mira["position"] == "left" and mira["bottom"] == pytest.approx(720, abs=1)
    assert mira["height"] == pytest.approx(mira["width"] * 2, abs=1)
    assert mira["x"] + mira["width"] / 2 == pytest.approx(1280 * 0.2, abs=1)
    assert choice["buttons"] == ["Go", "Stay"] and choice["name"] is None
    assert {item["position"] for item in choice["figures"]} == {"left", "center"}
    assert [item["position"] for item in moved["figures"]] == ["right"]
    assert moved["text"] == "Wait!" and moved["name"] == "Oren"
    assert ending["buttons"] == ["Play again"] and ending["text"] == "Gone."
    assert [item["position"] for item in ending["figures"]] == ["right"]


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

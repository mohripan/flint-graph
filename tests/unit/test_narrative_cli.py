import json
import shutil
from pathlib import Path

from flint_graph.cli.narrative import main

FIXTURE = Path(__file__).parents[1] / "fixtures/narrative/lantern_archive"


def test_creator_can_validate_and_play_a_route_without_application_services(
    tmp_path, capsys
) -> None:
    assert main(["validate", str(FIXTURE)]) == 0
    validation = json.loads(capsys.readouterr().out)
    assert validation["valid"] is True
    assert validation["story_id"] == "lantern_archive"
    actions = tmp_path / "actions.json"
    actions.write_text('["advance","choose:leave"]', encoding="utf-8")
    save = tmp_path / "game-save.json"

    assert main(["play", str(FIXTURE), "--actions", str(actions), "--save-out", str(save)]) == 0
    output = json.loads(capsys.readouterr().out)

    assert output["state"]["ending"] == "quiet"
    assert [frame["node_id"] for frame in output["frames"]] == [
        "arrival",
        "approach_choice",
        "quiet_end",
    ]
    assert json.loads(save.read_bytes())["ending"] == "quiet"


def test_invalid_input_reports_safe_json_and_nonzero_exit(tmp_path, capsys) -> None:
    assert main(["validate", str(tmp_path / "private-canary")]) == 1
    output = capsys.readouterr()
    assert json.loads(output.err)["error"] == "missing_file"
    assert "private-canary" not in output.err
    assert output.out == ""


def test_save_out_refuses_to_replace_an_existing_file(tmp_path, capsys) -> None:
    actions = tmp_path / "actions.json"
    actions.write_text("[]", encoding="utf-8")
    save = tmp_path / "save.json"
    save.write_bytes(b"creator file")

    assert main(["play", str(FIXTURE), "--actions", str(actions), "--save-out", str(save)]) == 1

    assert save.read_bytes() == b"creator file"
    assert json.loads(capsys.readouterr().err)["error"] == "output_exists"


def test_interactive_output_cannot_emit_terminal_commands(tmp_path, capsys, monkeypatch) -> None:
    root = tmp_path / "game"
    shutil.copytree(FIXTURE, root)
    story = json.loads((root / "story.json").read_bytes())
    story["nodes"]["arrival"]["text"] = "Untrusted \x1b]52;clipboard\x07 text"
    (root / "story.json").write_text(json.dumps(story), encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda _: "q")

    assert main(["play", str(root), "--interactive"]) == 0

    output = capsys.readouterr().out
    assert "\x1b" not in output
    assert "\x07" not in output


def test_interactive_choice_input_is_bounded_and_does_not_crash(
    tmp_path, capsys, monkeypatch
) -> None:
    answers = iter(["", "9" * 5000, "²", "q"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    assert main(["play", str(FIXTURE), "--interactive"]) == 0

    assert "Choose a listed number." in capsys.readouterr().out


def large_game(root: Path) -> Path:
    game = root / "large"
    game.mkdir()
    story = {
        "schema_version": "1",
        "id": "large",
        "title": "Large state",
        "language": "en",
        "entry": "start",
        "characters": {},
        "assets": {},
        "variables": {
            f"label_{i}": {"type": "enum", "values": ["x" * 16384], "initial": "x" * 16384}
            for i in range(80)
        },
        "nodes": {
            "start": {"type": "line", "text_id": "start_text", "text": "Loop.", "next": "start"},
            "finish": {"type": "end", "text_id": "end_text", "text": "End.", "ending": "done"},
        },
    }
    (game / "story.json").write_text(json.dumps(story), encoding="utf-8")
    (game / "NOTICES.txt").write_text("Original tests.", encoding="utf-8")
    return game


def test_scripted_trace_has_a_cumulative_output_budget(tmp_path, capsys) -> None:
    game = large_game(tmp_path)
    actions = tmp_path / "actions.json"
    actions.write_text(json.dumps(["advance"] * 10), encoding="utf-8")

    assert main(["play", str(game), "--actions", str(actions)]) == 1

    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"] == "trace_size_limit"


def test_cli_can_load_a_valid_save_larger_than_one_megabyte(tmp_path, capsys) -> None:
    from flint_graph.narrative import Player, load_package

    game = large_game(tmp_path)
    save = tmp_path / "large-save.json"
    save.write_bytes(Player(load_package(game)).save())
    actions = tmp_path / "actions.json"
    actions.write_text("[]", encoding="utf-8")

    assert main(["play", str(game), "--actions", str(actions), "--load", str(save)]) == 0

    assert len(json.loads(capsys.readouterr().out)["state"]["variables"]) == 80


def test_creator_can_export_godot_source_through_the_registered_cli_seam(tmp_path, capsys) -> None:
    output = tmp_path / "my-game"

    assert main(["export-godot", str(FIXTURE), "--output", str(output)]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["godot_version"] == "4.7.2.stable"
    assert (output / "project.godot").is_file()


def test_cli_refuses_to_export_inside_its_source_package(tmp_path, capsys) -> None:
    root = tmp_path / "source"
    shutil.copytree(FIXTURE, root)

    assert main(["export-godot", str(root), "--output", str(root / "export")]) == 1

    assert not (root / "export").exists()
    assert json.loads(capsys.readouterr().err)["error"] == "unsafe_output_path"

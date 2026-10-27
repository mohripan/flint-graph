"""Local authored-game validation and reference play; no application startup."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from flint_graph.narrative import PackageError, Player, PlayerError, load_package
from flint_graph.narrative.export import ExportError, export_godot
from flint_graph.narrative.json_format import parse_json
from flint_graph.narrative.player import SAVE_LIMIT

TRACE_LIMIT = 8 * 1024 * 1024


def _input(path: Path, limit: int = 1024 * 1024) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise PlayerError("input_size_limit")
    return data


def _append_frame(
    frames: list[dict[str, Any]], player: Player, action: str | None, used: int
) -> int:
    frame = player.frame(action)
    # ASCII JSON makes character count equal byte count; reject before retaining
    # another frame or constructing the combined output string.
    used += len(json.dumps(frame, ensure_ascii=True, separators=(",", ":"))) + 1
    if used > TRACE_LIMIT:
        raise PlayerError("trace_size_limit")
    frames.append(frame)
    return used


def _terminal(value: str) -> str:
    return "".join(
        char
        if char in "\n\t" or (ord(char) >= 32 and not 127 <= ord(char) <= 159)
        else f"\\u{ord(char):04x}"
        for char in value
    )


def _interactive(player: Player) -> None:
    while True:
        view = player.view
        if view["speaker_name"]:
            print(_terminal(view["speaker_name"]))
        print(_terminal(view["text"]))
        if player.state["status"] != "playing":
            return
        if view["type"] == "line":
            response = input("Enter to continue, q to stop: ")
            if response.lower() == "q":
                return
            player.act("advance")
        else:
            for index, option in enumerate(view["options"], 1):
                print(f"{index}. {_terminal(option['text'])}")
            response = input("Choice number, or q to stop: ")
            if response.lower() == "q":
                return
            if (
                1 <= len(response) <= 2
                and response.isascii()
                and response.isdecimal()
                and 1 <= int(response) <= len(view["options"])
            ):
                player.act("choose:" + view["options"][int(response) - 1]["id"])
            else:
                print("Choose a listed number.")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="flint-graph-narrative")
    subcommands = parser.add_subparsers(dest="command", required=True)
    validate = subcommands.add_parser("validate", help="Validate a local story package")
    validate.add_argument("package", type=Path)
    export = subcommands.add_parser(
        "export-godot", help="Create a new editable Godot source project"
    )
    export.add_argument("package", type=Path)
    export.add_argument("--output", type=Path, required=True)
    play = subcommands.add_parser("play", help="Play with fixed actions or an interactive terminal")
    play.add_argument("package", type=Path)
    mode = play.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--actions", type=Path, help="UTF-8 JSON array of advance/choose:<id> actions"
    )
    mode.add_argument("--interactive", action="store_true")
    play.add_argument("--load", type=Path, help="Restore a compatible local save")
    play.add_argument("--save-out", type=Path, help="Write a new save; existing files are refused")
    args = parser.parse_args(argv)
    try:
        package = load_package(args.package)
        result: dict[str, Any]
        if args.command == "validate":
            result = {
                "valid": True,
                "story_id": package.story["id"],
                "package_hash": package.content_hash,
                "warnings": [
                    {"code": warning.code, "location": warning.location}
                    for warning in package.warnings
                ],
            }
        elif args.command == "export-godot":
            if args.output.resolve().is_relative_to(args.package.resolve()):
                raise ExportError("unsafe_output_path")
            exported = export_godot(package, args.output)
            result = {
                "package_hash": exported.package_hash,
                "manifest_hash": exported.manifest_hash,
                "file_count": exported.file_count,
                "godot_version": exported.godot_version,
            }
        else:
            player = Player(package)
            if args.load:
                player.load_save(_input(args.load, SAVE_LIMIT))
            frames: list[dict[str, Any]] = []
            if args.interactive:
                _interactive(player)
            else:
                used = _append_frame(frames, player, None, 0)
                actions = parse_json(_input(args.actions), limit=1024 * 1024)
                if (
                    type(actions) is not list
                    or len(actions) > 10000
                    or any(type(action) is not str or len(action) > 80 for action in actions)
                ):
                    raise PlayerError("invalid_actions")
                for action in actions:
                    player.act(action)
                    used = _append_frame(frames, player, action, used)
            if args.save_out:
                try:
                    with args.save_out.open("xb") as stream:
                        stream.write(player.save())
                except FileExistsError:
                    raise PlayerError("output_exists") from None
            result = {
                "state": player.state,
                "view": player.view,
                "frames": frames,
                "trace_complete": not args.interactive,
            }
        print(json.dumps(result, ensure_ascii=True, separators=(",", ":")))
        return 1 if args.command == "play" and result["state"]["status"] == "fault" else 0
    except (PackageError, PlayerError, ExportError) as error:
        print(json.dumps({"error": error.code}), file=sys.stderr)
        return 1
    except (OSError, EOFError, KeyboardInterrupt):
        print(json.dumps({"error": "local_io"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

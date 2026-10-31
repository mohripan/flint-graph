"""Deterministic reference execution for a validated authored game."""

from collections.abc import Iterable
from typing import Any

from flint_graph.narrative.json_format import parse_json
from flint_graph.narrative.validation import (
    INT_MAX,
    INT_MIN,
    POSITIONS,
    asset_of,
    fields,
    reference,
    typed_value,
)
from flint_graph.narrative.values import PackageError, StoryPackage, canonical_json

# All variable literals are bounded by a 5 MiB source package; leave a full MiB
# for integer growth, variable keys and fixed save metadata, not just small games.
SAVE_LIMIT = 6 * 1024 * 1024


class PlayerError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def evaluate_condition(condition: dict[str, Any], variables: dict[str, Any]) -> bool:
    op = condition["op"]
    if op == "all":
        return all(evaluate_condition(child, variables) for child in condition["children"])
    if op == "any":
        return any(evaluate_condition(child, variables) for child in condition["children"])
    if op == "not":
        return not evaluate_condition(condition["child"], variables)
    left, right = variables[condition["variable"]], condition["value"]
    if op == "eq":
        return bool(left == right)
    if op == "ne":
        return bool(left != right)
    if op == "lt":
        return bool(left < right)
    if op == "le":
        return bool(left <= right)
    if op == "gt":
        return bool(left > right)
    return bool(left >= right)  # ge; the package boundary rejects unknown operations.


def cg_gallery_assets(story: dict[str, Any]) -> list[str]:
    """First structural use: entry-first DFS, declared target order, then orphan IDs.

    JSON object order is not semantic (packages canonicalize it). Visit each node
    once, including loops and both branches, and include unreachable CGs as locked.
    """
    if story["schema_version"] != "2":
        return []
    nodes = story["nodes"]
    pending = [*reversed(sorted(nodes)), story["entry"]]
    visited: set[str] = set()
    assets: dict[str, None] = {}
    while pending:
        key = pending.pop()
        if key in visited:
            continue
        visited.add(key)
        node = nodes[key]
        if node["type"] == "stage" and node.get("cg") is not None:
            assets[node["cg"]] = None
        kind = node["type"]
        targets = (
            [node["next"]]
            if kind in ("line", "stage", "set")
            else [item["target"] for item in node["options"]]
            if kind == "choice"
            else [node["if_true"], node["if_false"]]
            if kind == "branch"
            else []
        )
        pending.extend(reversed(targets))
    return list(assets)


class Player:
    """One local session; public state is a defensive snapshot."""

    def __init__(self, package: StoryPackage, *, seen_cgs: Iterable[str] = ()) -> None:
        self._package = package
        self._package_hash = package.content_hash
        self._story = package.story
        # v2 (ADR 0040): the stage persists across screens and is part of every save.
        self._v2 = self._story["schema_version"] == "2"
        self._stage: dict[str, Any] = {"background": None, "cg": None, "characters": []}
        self._cg_assets = cg_gallery_assets(self._story)
        self._seen_cgs = {key for key in seen_cgs if type(key) is str and key in self._cg_assets}
        self._variables = {key: value["initial"] for key, value in self._story["variables"].items()}
        self._node_id = self._story["entry"]
        self._status = "playing"
        self._ending: str | None = None
        self._fault: str | None = None
        self._generation = 0
        self._settle(self._node_id)
        self._unlock_cg()

    @property
    def package(self) -> StoryPackage:
        return self._package

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def gallery(self) -> list[dict[str, Any]]:
        return [{"id": key, "unlocked": key in self._seen_cgs} for key in self._cg_assets]

    @property
    def seen_cgs(self) -> list[str]:
        return [key for key in self._cg_assets if key in self._seen_cgs]

    def _unlock_cg(self) -> None:
        if self._stage["cg"] in self._cg_assets:
            self._seen_cgs.add(self._stage["cg"])

    @property
    def state(self) -> dict[str, Any]:
        state = {
            "package_hash": self._package_hash,
            "node_id": self._node_id,
            "variables": dict(self._variables),
            "status": self._status,
            "ending": self._ending,
            "fault": self._fault,
        }
        if self._v2:
            state["stage"] = self._stage_copy()
        return state

    def _stage_copy(self) -> dict[str, Any]:
        return {
            "background": self._stage["background"],
            "cg": self._stage["cg"],
            "characters": [dict(item) for item in self._stage["characters"]],
        }

    @property
    def view(self) -> dict[str, Any]:
        if self._v2:
            return self._view_v2()
        node = self._story["nodes"][self._node_id]
        if self._status == "fault":
            return {
                "type": "fault",
                "text_id": None,
                "text": "The game cannot continue.",
                "speaker": None,
                "speaker_name": None,
                "portrait": None,
                "background": None,
                "options": [],
            }
        speaker = node.get("speaker") if node["type"] == "line" else None
        return {
            "type": node["type"],
            "text_id": node["text_id"],
            "text": node["text"],
            "speaker": speaker,
            "speaker_name": self._story["characters"][speaker]["name"] if speaker else None,
            "portrait": node.get("portrait") if node["type"] == "line" else None,
            "background": node.get("background") if node["type"] == "line" else None,
            "options": [
                {"id": option["id"], "text_id": option["text_id"], "text": option["text"]}
                for option in self._options()
            ],
        }

    def _view_v2(self) -> dict[str, Any]:
        """The screen is the current text plus the persistent stage, including faults."""
        node = self._story["nodes"][self._node_id]
        if self._status == "fault":
            return {
                "type": "fault",
                "text_id": None,
                "text": "The game cannot continue.",
                "speaker": None,
                "speaker_name": None,
                "speaker_color": None,
                "stage": self._stage_copy(),
                "voice": None,
                "options": [],
            }
        speaker = node.get("speaker") if node["type"] == "line" else None
        character = self._story["characters"][speaker] if speaker else None
        return {
            "type": node["type"],
            "text_id": node["text_id"],
            "text": node["text"],
            "speaker": speaker,
            "speaker_name": character["name"] if character else None,
            "speaker_color": character.get("color") if character else None,
            "stage": self._stage_copy(),
            # The settled line's voice clip (ADR 0043); a voice without audio is silent.
            "voice": node.get("voice", {}).get("audio") if node["type"] == "line" else None,
            "options": [
                {"id": option["id"], "text_id": option["text_id"], "text": option["text"]}
                for option in self._options()
            ],
        }

    def frame(self, action: str | None = None) -> dict[str, Any]:
        """Cross-runtime trace without rendering-specific strings or pixels."""
        frame = {
            "action": action,
            "node_id": self._node_id,
            "text_id": self.view["text_id"],
            "option_ids": [option["id"] for option in self.view["options"]],
            "variables": dict(self._variables),
            "status": self._status,
            "ending": self._ending,
            "fault": self._fault,
        }
        if self._v2:
            frame["stage"] = self._stage_copy()
            frame["voice"] = self.view["voice"]
        return frame

    def save(self) -> bytes:
        return canonical_json({"schema_version": "2" if self._v2 else "1", **self.state})

    def load_save(self, data: bytes) -> dict[str, Any]:
        """Validate completely before replacing any running state; never replay effects."""
        try:
            saved = parse_json(data, limit=SAVE_LIMIT)
            required = {
                "schema_version",
                "package_hash",
                "node_id",
                "variables",
                "status",
                "ending",
                "fault",
            }
            fields(saved, required | ({"stage"} if self._v2 else set()), set(), "save")
            if (
                saved["schema_version"] != ("2" if self._v2 else "1")
                or saved["package_hash"] != self._package_hash
            ):
                raise PackageError("invalid_save")
            stage = self._checked_stage(saved["stage"]) if self._v2 else None
            node_id = reference(saved["node_id"], self._story["nodes"], "save.node_id")
            declarations = self._story["variables"]
            variables = fields(saved["variables"], set(declarations), set(), "save.variables")
            for key, value in variables.items():
                typed_value(value, declarations[key], "save.variables")
            node = self._story["nodes"][node_id]
            kind, status = node["type"], saved["status"]
            valid = False
            if status == "playing" and saved["ending"] is None and saved["fault"] is None:
                valid = kind == "line" or (
                    kind == "choice"
                    and any(
                        "condition" not in option
                        or evaluate_condition(option["condition"], variables)
                        for option in node["options"]
                    )
                )
            elif status == "ended" and saved["fault"] is None:
                valid = kind == "end" and saved["ending"] == node["ending"]
            elif status == "fault" and saved["ending"] is None:
                fault = saved["fault"]
                if fault == "no_available_choices" and kind == "choice":
                    valid = not any(
                        "condition" not in option
                        or evaluate_condition(option["condition"], variables)
                        for option in node["options"]
                    )
                elif fault == "automatic_transition_limit":
                    valid = kind in ("set", "branch", "stage")
                elif fault == "integer_overflow" and kind == "set":
                    updated = dict(variables)
                    for operation in node["operations"]:
                        value = operation["value"]
                        if operation["op"] == "increment":
                            value += updated[operation["variable"]]
                            if not INT_MIN <= value <= INT_MAX:
                                valid = True
                                break
                        updated[operation["variable"]] = value
            if not valid:
                raise PackageError("invalid_save")
        except PackageError:
            raise PlayerError("invalid_save") from None
        self._node_id, self._variables = node_id, dict(variables)
        self._status, self._ending, self._fault = status, saved["ending"], saved["fault"]
        if stage is not None:
            self._stage = stage
            self._unlock_cg()
        self._generation += 1
        return self.state

    def _checked_stage(self, value: Any) -> dict[str, Any]:
        """A saved stage: known image background and characters in canonical slots."""
        stage = fields(value, {"background", "characters"}, {"cg"}, "save.stage")
        cg = stage.get("cg")
        if cg is not None:
            asset_of(cg, self._story["assets"], "image", "save.stage.cg")
        background = stage["background"]
        if background is not None:
            asset_of(background, self._story["assets"], "image", "save.stage")
        characters = stage["characters"]
        if type(characters) is not list or len(characters) > len(POSITIONS):
            raise PackageError("invalid_save")
        seen: set[str] = set()
        order: list[int] = []
        for item in characters:
            fields(item, {"id", "sprite", "position"}, {"x"}, "save.stage")
            if "x" in item and (type(item["x"]) is not int or not 0 <= item["x"] <= 100):
                raise PackageError("invalid_save")
            character = reference(item["id"], self._story["characters"], "save.stage")
            reference(
                item["sprite"],
                self._story["characters"][character].get("sprites", {}),
                "save.stage",
            )
            if item["position"] not in POSITIONS or character in seen:
                raise PackageError("invalid_save")
            seen.add(character)
            order.append(POSITIONS.index(item["position"]))
        if order != sorted(set(order)):
            raise PackageError("invalid_save")  # Unique positions, left to right.
        return {
            "background": background,
            "cg": cg,
            "characters": [dict(item) for item in characters],
        }

    def _options(self) -> list[dict[str, Any]]:
        node = self._story["nodes"][self._node_id]
        if node["type"] != "choice":
            return []
        return [
            option
            for option in node["options"]
            if "condition" not in option or evaluate_condition(option["condition"], self._variables)
        ]

    def act(self, action: str, *, expected_generation: int | None = None) -> dict[str, Any]:
        if self._status != "playing" or (
            expected_generation is not None
            and (type(expected_generation) is not int or expected_generation != self._generation)
        ):
            raise PlayerError("invalid_action")
        node = self._story["nodes"][self._node_id]
        if action == "advance" and node["type"] == "line":
            target = node["next"]
        elif type(action) is str and action.startswith("choose:") and node["type"] == "choice":
            options = {option["id"]: option for option in self._options()}
            selected = options.get(action[7:])
            if selected is None:
                raise PlayerError("invalid_action")
            target = selected["target"]
        else:
            raise PlayerError("invalid_action")
        self._settle(target)
        self._unlock_cg()
        self._generation += 1
        return self.state

    def _staged(self, node: dict[str, Any]) -> dict[str, Any]:
        """Apply one stage node to a copy: hide, then show (a slot holds one character)."""
        background = node["background"] if "background" in node else self._stage["background"]
        present = {
            item["id"]: dict(item)
            for item in self._stage["characters"]
            if item["id"] not in node.get("hide", [])
        }
        for entry in node.get("show", []):
            for other in [
                key for key, item in present.items() if item["position"] == entry["position"]
            ]:
                if other != entry["character"]:
                    del present[other]
            present[entry["character"]] = {
                "id": entry["character"],
                "sprite": entry["sprite"],
                "position": entry["position"],
                # An explicit horizontal place belongs to this placement only.
                **({"x": entry["x"]} if "x" in entry else {}),
            }
        ordered = sorted(present.values(), key=lambda item: POSITIONS.index(item["position"]))
        return {
            "background": background,
            "cg": node.get("cg", self._stage["cg"]),
            "characters": ordered,
        }

    def _expressed(self, speaker: str, expression: str) -> dict[str, Any]:
        stage = self._stage_copy()
        for item in stage["characters"]:
            if item["id"] == speaker:
                item["sprite"] = expression
        return stage

    def _settle(self, node_id: str) -> None:
        transitions = 0
        self._status, self._ending, self._fault = "playing", None, None
        while True:
            self._node_id = node_id
            node = self._story["nodes"][node_id]
            kind = node["type"]
            if kind in ("line", "choice"):
                if kind == "choice" and not self._options():
                    self._status, self._fault = "fault", "no_available_choices"
                if kind == "line" and "expression" in node:
                    # Applied once when the line settles; saves store the result.
                    self._stage = self._expressed(node["speaker"], node["expression"])
                return
            if kind == "end":
                self._status, self._ending = "ended", node["ending"]
                return
            if transitions >= 1000:
                self._status, self._fault = "fault", "automatic_transition_limit"
                return
            transitions += 1
            if kind == "branch":
                node_id = (
                    node["if_true"]
                    if evaluate_condition(node["condition"], self._variables)
                    else node["if_false"]
                )
            elif kind == "stage":
                self._stage = self._staged(node)
                node_id = node["next"]
            else:
                updated = dict(self._variables)
                for operation in node["operations"]:
                    variable = operation["variable"]
                    value = operation["value"]
                    if operation["op"] == "increment":
                        value += updated[variable]
                        if not INT_MIN <= value <= INT_MAX:
                            self._status, self._fault = "fault", "integer_overflow"
                            return
                    updated[variable] = value
                self._variables = updated
                node_id = node["next"]

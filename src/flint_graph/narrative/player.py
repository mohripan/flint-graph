"""Deterministic reference execution for a validated authored game."""

from typing import Any

from flint_graph.narrative.json_format import parse_json
from flint_graph.narrative.validation import INT_MAX, INT_MIN, fields, reference, typed_value
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


class Player:
    """One local session; public state is a defensive snapshot."""

    def __init__(self, package: StoryPackage) -> None:
        self._package = package
        self._package_hash = package.content_hash
        self._story = package.story
        self._variables = {key: value["initial"] for key, value in self._story["variables"].items()}
        self._node_id = self._story["entry"]
        self._status = "playing"
        self._ending: str | None = None
        self._fault: str | None = None
        self._generation = 0
        self._settle(self._node_id)

    @property
    def package(self) -> StoryPackage:
        return self._package

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def state(self) -> dict[str, Any]:
        return {
            "package_hash": self._package_hash,
            "node_id": self._node_id,
            "variables": dict(self._variables),
            "status": self._status,
            "ending": self._ending,
            "fault": self._fault,
        }

    @property
    def view(self) -> dict[str, Any]:
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

    def frame(self, action: str | None = None) -> dict[str, Any]:
        """Cross-runtime trace without rendering-specific strings or pixels."""
        return {
            "action": action,
            "node_id": self._node_id,
            "text_id": self.view["text_id"],
            "option_ids": [option["id"] for option in self.view["options"]],
            "variables": dict(self._variables),
            "status": self._status,
            "ending": self._ending,
            "fault": self._fault,
        }

    def save(self) -> bytes:
        return canonical_json({"schema_version": "1", **self.state})

    def load_save(self, data: bytes) -> dict[str, Any]:
        """Validate completely before replacing any running state; never replay effects."""
        try:
            saved = parse_json(data, limit=SAVE_LIMIT)
            fields(
                saved,
                {
                    "schema_version",
                    "package_hash",
                    "node_id",
                    "variables",
                    "status",
                    "ending",
                    "fault",
                },
                set(),
                "save",
            )
            if saved["schema_version"] != "1" or saved["package_hash"] != self._package_hash:
                raise PackageError("invalid_save")
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
                    valid = kind in ("set", "branch")
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
        self._generation += 1
        return self.state

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
        self._generation += 1
        return self.state

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

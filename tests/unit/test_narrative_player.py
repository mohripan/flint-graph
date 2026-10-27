import json
from pathlib import Path

import pytest

from flint_graph.narrative import Player, PlayerError, load_package

FIXTURES = Path(__file__).parents[1] / "fixtures/narrative"
ROUTES = json.loads((FIXTURES / "lantern_routes.json").read_text(encoding="utf-8"))["routes"]


@pytest.mark.parametrize("route", ROUTES, ids=[item["id"] for item in ROUTES])
def test_original_routes_reach_the_independently_authored_outcomes(route: dict) -> None:
    player = Player(load_package(FIXTURES / "lantern_archive"))

    for action in route["actions"]:
        player.act(action)

    assert player.state["status"] == "ended"
    assert player.state["ending"] == route["ending"]
    assert player.state["variables"] == route["variables"]


def test_display_is_node_derived_and_returned_state_cannot_mutate_the_session() -> None:
    player = Player(load_package(FIXTURES / "lantern_archive"))
    assert player.view["portrait"] == "archivist"
    assert player.view["background"] == "archive"
    assert player.view["speaker_name"] == "Mira, the archivist"
    state = player.state
    state["variables"]["trust"] = 999

    player.act("advance")

    assert player.state["variables"]["trust"] == 0
    assert player.view["text"] == "How will you approach the mystery?"
    assert player.view["portrait"] is None
    assert player.view["background"] is None
    assert [option["id"] for option in player.view["options"]] == ["listen", "leave", "accuse"]


@pytest.mark.parametrize("action", ["choose:listen", "choose:missing", "advance:extra", "", None])
def test_invalid_actions_preserve_the_running_session(action: str) -> None:
    player = Player(load_package(FIXTURES / "lantern_archive"))
    before = player.state

    with pytest.raises(PlayerError, match="invalid_action"):
        player.act(action)

    assert player.state == before


def test_route_trace_reports_exact_nodes_options_and_state() -> None:
    player = Player(load_package(FIXTURES / "lantern_archive"))
    frames = [player.frame()]
    actions = ["advance", "choose:listen", "advance", "choose:ask_letter", "advance"]
    for action in actions:
        player.act(action)
        frames.append(player.frame(action))

    assert [frame["node_id"] for frame in frames] == [
        "arrival",
        "approach_choice",
        "letter_clue",
        "inquiry",
        "promise",
        "restored_end",
    ]
    assert frames[3]["option_ids"] == ["ask_letter", "leave"]
    assert frames[-1]["variables"] == {"trust": 1, "letter_known": True, "approach": "careful"}
    assert frames[-1]["ending"] == "restored"
    assert frames[-1]["fault"] is None


def local_player(tmp_path: Path, nodes: dict, variables: dict | None = None) -> Player:
    story = {
        "schema_version": "1",
        "id": "test_game",
        "title": "State tests",
        "language": "en",
        "entry": "start",
        "characters": {},
        "assets": {},
        "variables": variables or {},
        "nodes": {
            "finish": {"type": "end", "ending": "done", "text_id": "done_text", "text": "Done."},
            **nodes,
        },
    }
    (tmp_path / "story.json").write_text(json.dumps(story), encoding="utf-8")
    (tmp_path / "NOTICES.txt").write_text("Original test writing.", encoding="utf-8")
    return Player(load_package(tmp_path))


@pytest.mark.parametrize(
    ("op", "literal", "expected"),
    [
        ("eq", 2, "done"),
        ("eq", 3, "other"),
        ("ne", 3, "done"),
        ("ne", 2, "other"),
        ("lt", 3, "done"),
        ("lt", 2, "other"),
        ("le", 2, "done"),
        ("le", 1, "other"),
        ("gt", 1, "done"),
        ("gt", 2, "other"),
        ("ge", 2, "done"),
        ("ge", 3, "other"),
    ],
)
def test_typed_comparisons_choose_the_correct_branch(
    tmp_path: Path,
    op: str,
    literal: int,
    expected: str,
) -> None:
    player = local_player(
        tmp_path,
        {
            "start": {
                "type": "branch",
                "condition": {"op": op, "variable": "count", "value": literal},
                "if_true": "finish",
                "if_false": "other",
            },
            "other": {"type": "end", "ending": "other", "text_id": "other_text", "text": "Other."},
        },
        {"count": {"type": "int", "initial": 2}},
    )

    assert player.state["ending"] == expected


def test_every_valid_large_enum_state_can_reload_its_own_save(tmp_path: Path) -> None:
    variables = {
        f"label_{i}": {"type": "enum", "values": ["x" * 16384], "initial": "x" * 16384}
        for i in range(80)
    }
    player = local_player(
        tmp_path,
        {
            "start": {
                "type": "line",
                "text_id": "large_text",
                "text": "Large state.",
                "next": "finish",
            },
        },
        variables,
    )
    saved = player.save()
    assert len(saved) > 1024 * 1024
    before = player.state

    player.load_save(saved)

    assert player.state == before


def test_callback_from_an_older_screen_is_rejected_even_after_a_loop(tmp_path: Path) -> None:
    player = local_player(
        tmp_path,
        {
            "start": {"type": "line", "text_id": "loop_text", "text": "Loop.", "next": "start"},
        },
    )
    generation = player.generation
    player.act("advance", expected_generation=generation)
    before = player.state

    with pytest.raises(PlayerError, match="invalid_action"):
        player.act("advance", expected_generation=generation)

    assert player.state == before


@pytest.mark.parametrize(("initial", "increment"), [(2147483647, 1), (-2147483648, -1)])
def test_overflow_rolls_back_every_operation_in_its_set_node(
    tmp_path: Path,
    initial: int,
    increment: int,
) -> None:
    player = local_player(
        tmp_path,
        {
            "start": {
                "type": "set",
                "next": "finish",
                "operations": [
                    {"op": "set", "variable": "known", "value": True},
                    {"op": "increment", "variable": "count", "value": increment},
                ],
            },
        },
        {"count": {"type": "int", "initial": initial}, "known": {"type": "bool", "initial": False}},
    )

    assert player.state["status"] == "fault"
    assert player.state["fault"] == "integer_overflow"
    assert player.state["variables"] == {"known": False, "count": initial}


def test_automatic_loop_faults_at_the_documented_bound(tmp_path: Path) -> None:
    player = local_player(
        tmp_path,
        {
            "start": {
                "type": "set",
                "next": "start",
                "operations": [
                    {"op": "increment", "variable": "count", "value": 1},
                ],
            },
        },
        {"count": {"type": "int", "initial": 0}},
    )

    assert player.state["fault"] == "automatic_transition_limit"
    assert player.state["variables"]["count"] == 1000


def test_choice_with_no_available_options_faults_instead_of_hanging(tmp_path: Path) -> None:
    player = local_player(
        tmp_path,
        {
            "start": {
                "type": "choice",
                "text_id": "prompt",
                "text": "Choose.",
                "options": [
                    {
                        "id": "locked",
                        "text_id": "locked_text",
                        "text": "Locked",
                        "target": "finish",
                        "condition": {"op": "eq", "variable": "known", "value": True},
                    },
                ],
            },
        },
        {"known": {"type": "bool", "initial": False}},
    )

    assert player.state["fault"] == "no_available_choices"
    before = player.state
    with pytest.raises(PlayerError):
        player.act("choose:locked")
    assert player.state == before


def test_real_loop_reapplies_assignments_but_view_reads_do_not(tmp_path: Path) -> None:
    player = local_player(
        tmp_path,
        {
            "start": {
                "type": "set",
                "next": "show",
                "operations": [
                    {"op": "increment", "variable": "count", "value": 1},
                ],
            },
            "show": {"type": "line", "text_id": "show_text", "text": "Again.", "next": "start"},
        },
        {"count": {"type": "int", "initial": 0}},
    )

    assert player.view == player.view
    assert player.state["variables"]["count"] == 1
    player.act("advance")
    assert player.state["variables"]["count"] == 2


def test_save_at_a_choice_restores_state_and_clears_previous_visuals() -> None:
    package = load_package(FIXTURES / "lantern_archive")
    player = Player(package)
    player.act("advance")
    expected_state, expected_view = player.state, player.view
    saved = player.save()
    player.act("choose:listen")
    assert player.view["portrait"] == "archivist"

    player.load_save(saved)

    assert player.state == expected_state
    assert player.view == expected_view
    assert player.view["portrait"] is None
    assert player.state["variables"]["trust"] == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "2"),
        ("package_hash", "0" * 64),
        ("node_id", "missing"),
        ("node_id", "earn_trust"),
        ("status", "ended"),
        ("ending", "restored"),
        ("fault", "integer_overflow"),
        ("extra", "private canary"),
        ("variables", {"trust": True, "letter_known": False, "approach": "careful"}),
        ("variables", {"trust": 0.0, "letter_known": False, "approach": "careful"}),
        ("variables", {"trust": 2147483648, "letter_known": False, "approach": "careful"}),
        ("variables", {}),
    ],
)
def test_invalid_save_never_replaces_the_running_game(field: str, value: object) -> None:
    player = Player(load_package(FIXTURES / "lantern_archive"))
    before = player.state
    saved = json.loads(player.save())
    saved[field] = value

    with pytest.raises(PlayerError, match="invalid_save"):
        player.load_save(json.dumps(saved).encode())

    assert player.state == before


@pytest.mark.parametrize(
    "source",
    [b"null", b'{"x":1,"x":2}', b'{"x":"\\ud800"}', b"[]", b"{" * 65, b" " * (1024 * 1024 + 1)],
    ids=["null", "duplicate", "surrogate", "array", "depth", "size"],
)
def test_malformed_save_bytes_are_safe_controlled_failures(source: bytes) -> None:
    player = Player(load_package(FIXTURES / "lantern_archive"))
    before = player.state

    with pytest.raises(PlayerError, match="invalid_save"):
        player.load_save(source)

    assert player.state == before


def test_save_restore_does_not_apply_a_set_twice(tmp_path: Path) -> None:
    player = local_player(
        tmp_path,
        {
            "start": {
                "type": "set",
                "next": "show",
                "operations": [
                    {"op": "increment", "variable": "count", "value": 1},
                ],
            },
            "show": {"type": "line", "text_id": "show_text", "text": "Wait.", "next": "finish"},
        },
        {"count": {"type": "int", "initial": 0}},
    )
    saved = player.save()
    player.act("advance")

    player.load_save(saved)

    assert player.state["variables"]["count"] == 1
    assert player.state["node_id"] == "show"


def test_ended_save_restores_the_same_terminal_screen() -> None:
    package = load_package(FIXTURES / "lantern_archive")
    original = Player(package)
    original.act("advance")
    original.act("choose:leave")
    restored = Player(package)

    restored.load_save(original.save())

    assert restored.state == original.state
    assert restored.view == original.view
    with pytest.raises(PlayerError):
        restored.act("advance")


@pytest.mark.parametrize(
    "fault", ["integer_overflow", "automatic_transition_limit", "no_available_choices"]
)
def test_fault_saves_restore_without_reexecuting_failed_nodes(tmp_path: Path, fault: str) -> None:
    variables = {
        "count": {"type": "int", "initial": 2147483647 if fault == "integer_overflow" else 0}
    }
    if fault == "no_available_choices":
        nodes = {
            "start": {
                "type": "choice",
                "text_id": "choose_text",
                "text": "Locked.",
                "options": [
                    {
                        "id": "locked",
                        "text_id": "locked_text",
                        "text": "Locked",
                        "target": "finish",
                        "condition": {"op": "eq", "variable": "count", "value": 1},
                    }
                ],
            }
        }
    else:
        nodes = {
            "start": {
                "type": "set",
                "operations": [{"op": "increment", "variable": "count", "value": 1}],
                "next": "finish" if fault == "integer_overflow" else "start",
            }
        }
    player = local_player(tmp_path, nodes, variables)
    assert player.state["fault"] == fault
    expected = player.state

    player.load_save(player.save())

    assert player.state == expected


@pytest.mark.parametrize(("op", "expected"), [("all", "other"), ("any", "done"), ("not", "done")])
def test_compound_boolean_conditions_drive_real_branches(
    tmp_path: Path, op: str, expected: str
) -> None:
    true = {"op": "eq", "variable": "known", "value": True}
    false = {"op": "eq", "variable": "known", "value": False}
    condition = (
        {"op": "not", "child": false} if op == "not" else {"op": op, "children": [true, false]}
    )
    player = local_player(
        tmp_path,
        {
            "start": {
                "type": "branch",
                "condition": condition,
                "if_true": "finish",
                "if_false": "other",
            },
            "other": {"type": "end", "text_id": "other_text", "text": "Other.", "ending": "other"},
        },
        {"known": {"type": "bool", "initial": True}},
    )

    assert player.state["ending"] == expected

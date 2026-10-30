"""Assistant proposals are bounded edit operations checked by the manual-save rules."""

import copy
import json

import pytest
from pydantic import ValidationError

from flint_graph.narrative import PackageError
from flint_graph.narrative.assistant.operations import (
    MAX_OPERATIONS,
    Proposal,
    apply_operations,
    check_proposal,
)
from flint_graph.narrative.validation import collect_story_diagnostics, validate_story


def story() -> dict:
    return {
        "schema_version": "1",
        "id": "harbor_bell",
        "title": "The Harbor Bell",
        "language": "en",
        "entry": "opening",
        "characters": {"oren": {"name": "Oren, the harbormaster"}},
        "variables": {
            "courage": {"type": "int", "initial": 0},
            "rope_found": {"type": "bool", "initial": False},
            "mood": {"type": "enum", "values": ["calm", "afraid"], "initial": "calm"},
        },
        "assets": {},
        "nodes": {
            "opening": {
                "type": "line",
                "text_id": "opening_text",
                "speaker": "oren",
                "text": "Fog has swallowed the harbor.",
                "next": "first_choice",
            },
            "first_choice": {
                "type": "choice",
                "text_id": "first_prompt",
                "text": "What do you do first?",
                "options": [
                    {
                        "id": "search",
                        "text_id": "search_option",
                        "text": "Search.",
                        "target": "find",
                    },
                    {
                        "id": "wait",
                        "text_id": "wait_option",
                        "text": "Wait.",
                        "target": "lost_end",
                        "condition": {"op": "ge", "variable": "courage", "value": 0},
                    },
                ],
            },
            "find": {
                "type": "set",
                "operations": [{"op": "set", "variable": "rope_found", "value": True}],
                "next": "check",
            },
            "check": {
                "type": "branch",
                "condition": {"op": "eq", "variable": "rope_found", "value": True},
                "if_true": "rung_end",
                "if_false": "lost_end",
            },
            "rung_end": {
                "type": "end",
                "text_id": "rung_text",
                "text": "It rings.",
                "ending": "rung",
            },
            "lost_end": {
                "type": "end",
                "text_id": "lost_text",
                "text": "Silence.",
                "ending": "lost",
            },
        },
    }


def mutated(change) -> dict:
    value = story()
    change(value)
    return value


INVALID = [
    mutated(lambda s: s.update(schema_version="2")),
    mutated(lambda s: s.update(title=" ")),
    mutated(lambda s: s.update(language="EN")),
    mutated(lambda s: s["characters"]["oren"].update(name="")),
    mutated(lambda s: s["variables"]["mood"].update(values=["calm", "calm"])),
    mutated(lambda s: s.update(entry="missing")),
    mutated(lambda s: s["nodes"]["opening"].update(next="missing")),
    mutated(lambda s: s["nodes"]["opening"].update(extra=True)),
    mutated(lambda s: s["nodes"]["lost_end"].update(text_id="rung_text")),
    mutated(lambda s: s["nodes"]["check"]["condition"].update(op="lt")),
    mutated(lambda s: s["nodes"]["find"]["operations"][0].update(op="increment")),
    mutated(lambda s: s["nodes"]["first_choice"]["options"][1].update(id="search")),
    mutated(
        lambda s: [
            s["nodes"][key].update(type="line", next="opening") or s["nodes"][key].pop("ending")
            for key in ("rung_end", "lost_end")
        ]
    ),
    mutated(lambda s: s["nodes"].update(BadKey={"type": "end"})),
    "not a story",
]


def first_error(value) -> tuple[str, str]:
    with pytest.raises(PackageError) as raised:
        validate_story(value)
    return raised.value.code, raised.value.location


@pytest.mark.parametrize("invalid", INVALID)
def test_collected_diagnostics_start_with_the_exact_manual_save_error(invalid):
    diagnostics, warnings = collect_story_diagnostics(invalid)
    assert (diagnostics[0].code, diagnostics[0].location) == first_error(invalid)
    assert warnings == ()


def test_valid_story_has_no_diagnostics_and_the_same_structural_warnings():
    value = story()
    value["nodes"]["orphan"] = {
        "type": "end",
        "text_id": "orphan_text",
        "text": "Alone.",
        "ending": "orphan",
    }
    diagnostics, warnings = collect_story_diagnostics(value)
    assert diagnostics == ()
    assert warnings == validate_story(value)
    assert [w.code for w in warnings] == ["structural_unreachable"]


def test_independent_problems_are_reported_together_in_story_order():
    value = story()
    value["title"] = ""
    value["nodes"]["opening"]["next"] = "nowhere"
    value["nodes"]["first_choice"]["options"][0]["target"] = "also_missing"
    value["nodes"]["rung_end"]["text"] = ""
    diagnostics, _ = collect_story_diagnostics(value)
    assert [(d.code, d.location) for d in diagnostics] == [
        ("invalid_text", "title"),
        ("unknown_reference", "nodes.opening.next"),
        ("unknown_reference", "nodes.first_choice.target"),
        ("invalid_text", "nodes.rung_end.text"),
    ]


def test_collection_is_bounded():
    value = story()
    for index in range(80):
        value["nodes"][f"bad_{index}"] = {
            "type": "line",
            "text_id": f"bad_{index}",
            "text": "x",
            "next": "gone",
        }
    diagnostics, _ = collect_story_diagnostics(value, limit=50)
    assert len(diagnostics) == 50
    assert len(collect_story_diagnostics(value, limit=3)[0]) == 3


def test_operations_add_connected_scenes_with_stable_derived_text_ids():
    base = story()
    before = copy.deepcopy(base)
    proposal = Proposal.model_validate(
        {
            "summary": "Oren asks for help before the ending.",
            "operations": [
                {
                    "op": "upsert_node",
                    "id": "plea",
                    "node": {
                        "type": "choice",
                        "text": "Will you help?",
                        "options": [
                            {"id": "yes", "text": "Yes.", "target": "rung_end"},
                            {"id": "no", "text": "No.", "target": "lost_end"},
                        ],
                    },
                },
                {
                    "op": "upsert_node",
                    "id": "opening",
                    "node": {
                        "type": "line",
                        "speaker": "oren",
                        "text": "Fog. Help me.",
                        "next": "plea",
                    },
                },
                {"op": "upsert_character", "id": "mira", "name": "Mira"},
                {
                    "op": "upsert_variable",
                    "id": "trust",
                    "declaration": {"type": "int", "initial": 0},
                },
                {"op": "set_title", "title": "The Harbor Bell, revised"},
            ],
        }
    )
    edit = apply_operations(base, proposal.operations)
    assert base == before, "The base revision's story is never mutated"
    nodes = edit.story["nodes"]
    assert nodes["plea"]["text_id"] == "plea_text"
    assert [o["text_id"] for o in nodes["plea"]["options"]] == ["plea_yes_option", "plea_no_option"]
    assert nodes["opening"]["text_id"] == "opening_text", "Replacing a scene keeps its text ID"
    assert edit.story["characters"]["mira"] == {"name": "Mira"}
    assert edit.story["title"] == "The Harbor Bell, revised"
    assert edit.touched == (
        "characters.mira",
        "nodes.opening",
        "nodes.plea",
        "title",
        "variables.trust",
    )
    check = check_proposal(base, proposal.operations)
    assert check.diagnostics == () and check.story == edit.story


def test_replaced_choice_keeps_option_text_ids_by_option_id():
    base = story()
    edit = apply_operations(
        base,
        Proposal.model_validate(
            {
                "summary": "Reword",
                "operations": [
                    {
                        "op": "upsert_node",
                        "id": "first_choice",
                        "node": {
                            "type": "choice",
                            "text": "First?",
                            "options": [
                                {"id": "wait", "text": "Wait a while.", "target": "lost_end"},
                                {"id": "climb", "text": "Climb.", "target": "rung_end"},
                            ],
                        },
                    },
                ],
            }
        ).operations,
    )
    options = edit.story["nodes"]["first_choice"]["options"]
    assert edit.story["nodes"]["first_choice"]["text_id"] == "first_prompt"
    assert [o["text_id"] for o in options] == ["wait_option", "first_choice_climb_option"]


def test_derived_text_ids_never_collide_or_exceed_the_id_limit():
    base = story()
    base["nodes"]["opening"]["text_id"] = "scene_text"
    long_id = "a" * 64
    edit = apply_operations(
        base,
        Proposal.model_validate(
            {
                "summary": "Add",
                "operations": [
                    {
                        "op": "upsert_node",
                        "id": "scene",
                        "node": {"type": "end", "text": "Done.", "ending": "done"},
                    },
                    {
                        "op": "upsert_node",
                        "id": long_id,
                        "node": {"type": "end", "text": "Long.", "ending": "long"},
                    },
                ],
            }
        ).operations,
    )
    derived = [edit.story["nodes"][key]["text_id"] for key in ("scene", long_id)]
    assert "scene_text" not in derived
    assert all(len(item) <= 64 and item[0].isalpha() for item in derived)
    assert (
        check_proposal(
            base,
            Proposal.model_validate(
                {
                    "summary": "Add",
                    "operations": [
                        {
                            "op": "upsert_node",
                            "id": "scene",
                            "node": {"type": "end", "text": "Done.", "ending": "done"},
                        },
                    ],
                }
            ).operations,
        ).diagnostics
        == ()
    )


@pytest.mark.parametrize(
    "operations,code",
    [
        ([{"op": "delete_node", "id": "unknown"}], "unknown_target"),
        ([{"op": "delete_character", "id": "unknown"}], "unknown_target"),
        ([{"op": "delete_variable", "id": "unknown"}], "unknown_target"),
        (
            [{"op": "set_title", "title": "A"}, {"op": "set_title", "title": "B"}],
            "duplicate_target",
        ),
        (
            [
                {"op": "delete_node", "id": "find"},
                {
                    "op": "upsert_node",
                    "id": "find",
                    "node": {"type": "end", "text": "x", "ending": "x"},
                },
            ],
            "duplicate_target",
        ),
    ],
)
def test_ambiguous_or_unknown_targets_are_rejected_before_validation(operations, code):
    parsed = Proposal.model_validate({"summary": "Edit", "operations": operations}).operations
    with pytest.raises(PackageError) as raised:
        apply_operations(story(), parsed)
    assert raised.value.code == code and raised.value.location.startswith("operations.")
    check = check_proposal(story(), parsed)
    assert check.story is None and check.diagnostics[0].code == code


def test_deleting_a_referenced_scene_is_reported_with_every_dangling_reference():
    check = check_proposal(
        story(),
        Proposal.model_validate(
            {
                "summary": "Cut",
                "operations": [
                    {"op": "delete_node", "id": "lost_end"},
                ],
            }
        ).operations,
    )
    assert check.story is None
    assert [(d.code, d.location) for d in check.diagnostics] == [
        ("unknown_reference", "nodes.first_choice.target"),
        ("unknown_reference", "nodes.check.if_false"),
    ]


def test_retargeting_and_deleting_together_is_valid_and_entry_can_move():
    check = check_proposal(
        story(),
        Proposal.model_validate(
            {
                "summary": "Cut",
                "operations": [
                    {"op": "delete_node", "id": "opening"},
                    {"op": "set_entry", "id": "first_choice"},
                ],
            }
        ).operations,
    )
    assert check.diagnostics == ()
    assert check.story["entry"] == "first_choice" and "opening" not in check.story["nodes"]
    assert check.touched == ("entry", "nodes.opening")


def test_proposals_are_bounded_and_strict():
    too_many = [{"op": "set_title", "title": f"T{i}"} for i in range(MAX_OPERATIONS + 1)]
    for payload in [
        {"summary": "x", "operations": too_many},
        {"summary": "x", "operations": [{"op": "rewrite_everything"}]},
        {"summary": "x", "operations": [{"op": "set_title", "title": "x", "extra": 1}]},
        {"summary": "", "operations": []},
        {"summary": "x" * 401, "operations": []},
    ]:
        with pytest.raises(ValidationError):
            Proposal.model_validate(payload)
    assert (
        Proposal.model_validate({"summary": "Nothing to change", "operations": []}).operations == []
    )


def test_oversized_results_fail_with_the_package_size_limit():
    huge = "x" * 16000
    operations = [
        {
            "op": "upsert_node",
            "id": f"n{i}",
            "node": {"type": "end", "text": huge, "ending": f"e{i}"},
        }
        for i in range(MAX_OPERATIONS)
    ]
    base = story()
    for index in range(300):
        base["nodes"][f"pad{index}"] = {
            "type": "end",
            "text_id": f"pad{index}",
            "text": huge,
            "ending": f"p{index}",
        }
    check = check_proposal(
        base, Proposal.model_validate({"summary": "Grow", "operations": operations}).operations
    )
    assert check.story is None
    assert [(d.code, d.location) for d in check.diagnostics] == [("size_limit", "story.json")]
    assert len(json.dumps(base)) < 5 * 1024 * 1024

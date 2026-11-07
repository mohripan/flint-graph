"""What counts as putting someone without a picture into a scene (ADR 0079)."""

from flint_graph.narrative.pictures import picture_diagnostics, without_pictures


def story(**nodes) -> dict:
    return {
        "schema_version": "2",
        "characters": {
            "ren": {"name": "Ren"},
            "mira": {"name": "Mira", "sprites": {"default": "x"}},
        },
        "nodes": nodes,
    }


def said_by(speaker) -> dict:
    return {"type": "line", "speaker": speaker, "text": "Hello."}


def showing(*names) -> dict:
    entries = [{"character": name, "sprite": "default", "position": "left"} for name in names]
    return {"type": "stage", "show": entries}


def test_a_new_line_or_a_new_stage_entry_needs_a_picture():
    assert without_pictures(story(), story(a=said_by("ren"))) == [("a", "ren")]
    assert without_pictures(story(), story(a=showing("ren"))) == [("a", "ren")]


def test_someone_with_a_picture_is_welcome():
    assert without_pictures(story(), story(a=said_by("mira"), b=showing("mira"))) == []


def test_what_was_already_there_stays_editable():
    base = story(a=said_by("ren"), b=showing("ren"))
    assert without_pictures(base, base) == []
    reworded = story(a={**said_by("ren"), "text": "Other words."}, b=showing("ren"))
    assert without_pictures(base, reworded) == []


def test_giving_a_saved_line_a_new_speaker_counts():
    assert without_pictures(story(a=said_by("mira")), story(a=said_by("ren"))) == [("a", "ren")]


def test_narration_and_other_steps_need_nothing():
    node = {"type": "line", "text": "Dusk."}
    assert without_pictures(story(), story(a=node, b={"type": "end", "text": "Done."})) == []


def test_a_story_from_before_stages_is_not_held_to_this():
    v1 = {**story(a=said_by("ren")), "schema_version": "1"}
    assert without_pictures(story(), v1) == []


def test_each_problem_says_where_it_is():
    found = picture_diagnostics(story(), story(a=said_by("ren"), b=showing("ren")))
    assert [(item.code, item.location) for item in found] == [
        ("needs_approved_picture", "nodes.a"),
        ("needs_approved_picture", "nodes.b"),
    ]

"""Public catalog rendering and immutable identity contract."""

import pytest

from flint_graph.prompts.catalog import PromptEntry, PromptError


def test_typed_text_rendering_rejects_bad_variables_and_substitutes_only_once():
    entry = PromptEntry.create(
        name="example.greeting",
        template="Hello {{name}} / {{count}}",
        catalog_version=1,
        variables_schema={
            "type": "object",
            "properties": {"name": {"type": "string"}, "count": {"type": "integer"}},
            "required": ["name", "count"],
            "additionalProperties": False,
        },
    )
    assert entry.render(name="{{count}}", count=3) == "Hello {{count}} / 3"
    for variables in (
        {"name": "Ren"},
        {"name": "Ren", "count": True},
        {"name": "Ren", "count": 3, "extra": "private"},
    ):
        with pytest.raises(PromptError, match="invalid_variables"):
            entry.render(**variables)
    assert "Ren" not in str(PromptError("invalid_variables"))


def test_lock_rejects_tampering_and_a_run_keeps_its_original_bundle():
    import json

    from flint_graph.prompts.source import LockedPromptSource, PromptBundle, use_snapshot

    entry = PromptEntry.create(name="example.greeting", template="Hello", catalog_version=1)
    first = PromptBundle.create([entry], source_revision="fixture", evaluation_record="fixture")
    source = LockedPromptSource.from_bytes(LockedPromptSource.pack([first], first.sha256))
    with use_snapshot(source.snapshot()):
        from flint_graph.prompts.source import current_snapshot

        assert current_snapshot().entry("example.greeting").render() == "Hello"
        changed = source.snapshot().entry("example.greeting").data
        changed["template"] = "mutated caller data"
        assert current_snapshot().entry("example.greeting").render() == "Hello"
    lock = json.loads(LockedPromptSource.pack([first], first.sha256))
    lock["bundles"][first.sha256]["entries"][0]["template"] = "unreviewed"
    with pytest.raises(PromptError, match="bundle_hash_mismatch"):
        LockedPromptSource.from_bytes(json.dumps(lock).encode())


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"version": 1, "negative": [], "blocked": "private"},
        {"version": 1, "negative": [4], "blocked": []},
    ],
)
def test_image_policy_rejects_invalid_config_before_activation(config):
    with pytest.raises(PromptError, match="invalid_policy_config"):
        PromptEntry.create(
            name="narrative.image.content_policy",
            kind="policy",
            template="",
            catalog_version=1,
            config=config,
        )

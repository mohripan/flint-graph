import pytest

from flint_graph.application.narrative_workflow import release_workflow_id, validate_release_payload

PAYLOAD = {
    "schema_version": "1",
    "tenant_id": "11111111-1111-4111-8111-111111111111",
    "release_id": "22222222-2222-4222-8222-222222222222",
    "job_id": "33333333-3333-4333-8333-333333333333",
}


def test_workflow_contract_contains_only_canonical_ids_and_a_fixed_version():
    parsed = validate_release_payload(PAYLOAD)
    assert parsed == PAYLOAD
    assert release_workflow_id(parsed) == "narrative-release-33333333-3333-4333-8333-333333333333"
    assert parsed is not PAYLOAD


@pytest.mark.parametrize(
    "payload",
    [
        {**PAYLOAD, "story_json": "PRIVATE_SOURCE_CANARY"},
        {**PAYLOAD, "schema_version": "2"},
        {**PAYLOAD, "job_id": "../../private"},
        {**PAYLOAD, "tenant_id": None},
        {key: value for key, value in PAYLOAD.items() if key != "release_id"},
        [],
    ],
)
def test_unknown_source_fields_or_invalid_ids_fail_with_only_a_safe_code(payload):
    with pytest.raises(ValueError, match=r"^Invalid narrative release payload$"):
        validate_release_payload(payload)

import pytest

from flint_graph.application.conversation_memory import interpret_followup


def test_prior_year_followup_preserves_scope_without_answer_transcript() -> None:
    result = interpret_followup(
        "What about the prior year?", "What was Acme Corporation revenue in 2017?"
    )
    assert result.mode == "resolved"
    assert result.query == "What was Acme Corporation revenue in 2016?"


@pytest.mark.parametrize(
    "question",
    ["How about the previous year?", "And what about prior year?", "WHAT ABOUT THE PRIOR YEAR?"],
)
def test_prior_year_variants_are_explicit(question) -> None:
    assert interpret_followup(question, "Acme revenue in 2017?").query == "Acme revenue in 2016?"


@pytest.mark.parametrize(
    "previous",
    [
        None,
        "Acme revenue?",
        "Acme revenue in 2017 versus 2016?",
        "Acme revenue in 1900?",
        "x" * 1001 + " 2017",
    ],
)
def test_unavailable_ambiguous_or_oversized_scope_clarifies(previous) -> None:
    result = interpret_followup("What about the prior year?", previous)
    assert result.mode == "clarification"
    assert result.query == "What about the prior year?"


def test_explicit_new_question_does_not_inherit_scope() -> None:
    result = interpret_followup("Where is Beta headquartered?", "Acme revenue in 2017?")
    assert result.mode == "independent"
    assert result.query == "Where is Beta headquartered?"


@pytest.mark.parametrize(
    "question", ["What about 2016?", "What was its revenue?", "And revenue?", "Tell me about them."]
)
def test_unimplemented_followup_shapes_clarify_instead_of_inventing_context(question) -> None:
    assert interpret_followup(question, "Acme revenue in 2017?").mode == "clarification"


def test_successive_prior_years_use_the_resolved_question() -> None:
    first = interpret_followup("What about the prior year?", "Acme revenue in 2017?")
    assert (
        interpret_followup("What about the prior year?", first.query).query
        == "Acme revenue in 2015?"
    )

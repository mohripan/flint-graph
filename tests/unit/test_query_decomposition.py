import pytest

from flint_graph.application.query_decomposition import coordinated_retrieval_queries


@pytest.mark.parametrize(
    "query,expected",
    [
        (
            "Give Acme's 2018 sales and Globex's 2019 profit.",
            ["Give Acme's 2018 sales", "Globex's 2019 profit."],
        ),
        (
            "Compare Acme\u2019s revenue versus North Star\u2019s profit.",
            ["Compare Acme\u2019s revenue", "North Star\u2019s profit."],
        ),
        (
            "Give Acme's sales and Globex's profit and Initech's costs.",
            ["Give Acme's sales", "Globex's profit", "Initech's costs."],
        ),
        (
            "Give Acme's sales and Globex's profit, "
            "identifying which figure belongs to which company.",
            ["Give Acme's sales", "Globex's profit"],
        ),
        (
            "Give Acme's sales and Globex's profit, including tax effects.",
            ["Give Acme's sales", "Globex's profit, including tax effects."],
        ),
    ],
)
def test_coordinated_named_sources_get_bounded_independent_queries(
    query: str,
    expected: list[str],
) -> None:
    assert coordinated_retrieval_queries(query) == expected


@pytest.mark.parametrize(
    "query",
    [
        "Give Acme's sales and profit.",
        "What are Acme's assets and its liabilities?",
        "How are Acme and Globex connected?",
        "Summarize the document.",
        "Give Acme's sales and Acme's costs.",
        "Give Acme's sales and Globex's costs and Initech's revenue and Umbrella's earnings.",
    ],
)
def test_rule_does_not_split_implicit_scope_or_silently_truncate_requests(query: str) -> None:
    assert coordinated_retrieval_queries(query) == [query]

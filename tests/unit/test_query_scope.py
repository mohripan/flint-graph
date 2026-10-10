import pytest

from flint_graph.application.query_scope import missing_financial_scope


@pytest.mark.parametrize(
    "query,missing",
    [
        ("What was revenue?", ["company_or_document", "reporting_period"]),
        ("what were the net sales?", ["company_or_document", "reporting_period"]),
        ("How much was operating income?", ["company_or_document", "reporting_period"]),
        ("What was revenue in 2019?", ["company_or_document"]),
        ("What were total assets for FY 2018?", ["company_or_document"]),
    ],
)
def test_bare_financial_values_require_explicit_scope(query: str, missing: list[str]) -> None:
    assert missing_financial_scope(query) == missing


@pytest.mark.parametrize(
    "query",
    [
        "What was Acme revenue in 2019?",
        "What was revenue for Acme?",
        "What is revenue?",
        "Define net income.",
        "How is revenue recognized?",
        "Summarize revenue across all reports.",
        "Compare revenue in 2018 and 2019.",
        "Can you summarize what's inside the document?",
        "What was the graph's degree?",
        "What was revenue growth for American Express in 2018?",
    ],
)
def test_scope_rule_does_not_claim_general_semantic_ambiguity_detection(query: str) -> None:
    assert missing_financial_scope(query) == []

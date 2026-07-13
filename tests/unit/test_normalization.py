from atlas_rag.application.entity_resolution import normalize_name


def test_normalize_casefolds_and_collapses_whitespace() -> None:
    assert normalize_name("  Acme   Corporation  ") == "acme corporation"
    assert normalize_name("ACME") == "acme"


def test_normalize_strips_punctuation_to_spaces() -> None:
    assert normalize_name("Acme Corp.") == "acme corp"
    assert normalize_name("J. Doe") == "j doe"
    assert normalize_name("Jean-Paul") == "jean paul"


def test_normalize_applies_unicode_nfkc() -> None:
    assert normalize_name("ＡＣＭＥ") == "acme"  # noqa: RUF001 - full-width input is the test
    assert normalize_name("Acme") == normalize_name("acme")


def test_normalize_returns_empty_for_punctuation_only() -> None:
    assert normalize_name("...") == ""
    assert normalize_name("   ") == ""

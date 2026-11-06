"""Invitation keys and usage-limit rules (ADR 0058)."""

import re

import pytest

from flint_graph.application.services.access import (
    DEFAULT_LIMITS,
    clean_limits,
    key_hash,
    limit_problem,
    new_key,
)


def test_keys_are_random_readable_and_hashed_after_normalizing():
    keys = {new_key() for _ in range(200)}
    assert len(keys) == 200
    for key in keys:
        assert re.fullmatch(r"FG(-[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{4}){4}", key), key
    key = new_key()
    # People retype keys: case, spaces and dashes do not matter.
    assert key_hash(key) == key_hash(" " + key.lower().replace("-", " ") + " ")
    assert key_hash(key) != key_hash(new_key())
    assert re.fullmatch(r"[0-9a-f]{64}", key_hash(key))


def test_limits_keep_known_kinds_and_whole_non_negative_numbers():
    assert clean_limits(DEFAULT_LIMITS) == DEFAULT_LIMITS
    assert clean_limits({"image": {"daily": 5}}) == {"image": {"daily": 5}}
    assert clean_limits({}) == {}
    for bad in (
        {"gpu": {"daily": 1}},
        {"image": {"weekly": 1}},
        {"image": {"daily": -1}},
        {"image": {"daily": 1.5}},
        {"image": {"daily": True}},
        {"image": 3},
        {"image": {"total": 10_000_001}},
    ):
        with pytest.raises(ValueError):
            clean_limits(bad)


def test_a_charge_is_refused_when_it_would_pass_either_limit():
    limits = {"image": {"daily": 4, "total": 10}}
    assert limit_problem(limits, "image", units=4, used_day=0, used_total=0) is None
    assert "all 4 images you can make in 24 hours" in limit_problem(limits, "image", 1, 4, 4)
    # Asking for more than is left says how many are left, not "try later".
    assert "only 1 of your 4 per 24 hours" in limit_problem(limits, "image", 2, 3, 3)
    assert "only 1 of the 10 your invitation includes" in limit_problem(limits, "image", 2, 0, 9)
    assert "all 10 images your invitation includes" in limit_problem(limits, "image", 1, 0, 10)
    # A kind without a limit, or with only one of the two, is open on the other side.
    assert limit_problem(limits, "voice", 500, used_day=500, used_total=5000) is None
    assert limit_problem({"voice": {"total": 3}}, "voice", 1, used_day=99, used_total=2) is None
    # Zero means the kind is not included in this invitation.
    assert "not included" in limit_problem({"training": {"total": 0}}, "training", 1, 0, 0)


def test_operators_need_a_verified_listed_email_or_the_admin_group(monkeypatch):
    from flint_graph.application.services.access import is_operator
    from flint_graph.application.services.authz import AuthenticatedPrincipal
    from flint_graph.config import Settings

    monkeypatch.setenv("FLINT_GRAPH_ACCESS_ADMIN_EMAILS", "Me@Example.com, ops@example.com")
    oidc = Settings(env="test", auth_mode="oidc", oidc_issuer="https://id", oidc_audience="fg")
    assert oidc.access_admin_emails == ["Me@Example.com", "ops@example.com"]

    def person(email, **claims):
        return AuthenticatedPrincipal("https://id", "s", email, None, claims)

    assert is_operator(person("me@example.com", email_verified=True), oidc)
    assert is_operator(person("ME@example.com", email_verified="true"), oidc)
    assert not is_operator(person("me@example.com"), oidc)
    assert not is_operator(person("someone@example.com", email_verified=True), oidc)
    grouped = oidc.model_copy(update={"oidc_system_admin_group": "studio-ops"})
    assert is_operator(person(None, groups=["studio-ops"]), grouped)
    assert not is_operator(person(None, groups="studio-ops"), grouped)
    # Local development trusts the configured dev email.
    dev = Settings(env="test", access_admin_emails=["dev@example.local"])
    assert is_operator(person("dev@example.local"), dev)

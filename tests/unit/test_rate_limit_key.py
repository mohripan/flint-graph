"""The public pre-auth key builder retains only bounded, normalized identities."""

import re

import pytest
from fastapi import Request

from flint_graph.api.middleware import rate_limit_key
from flint_graph.config import Settings


def request(path, headers):
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [(name.lower().encode(), value.encode()) for name, value in headers.items()],
            "client": ("127.0.0.2", 1234),
            "query_string": b"",
        }
    )


@pytest.mark.parametrize("path", ["/v1/narrative/projects", "/v1/search/lexical/some-id"])
def test_keys_never_retain_raw_credentials_or_unbounded_paths_and_workspaces(path):
    settings = Settings(
        _env_file=None,
        env="test",
        auth_mode="oidc",
        oidc_issuer="https://identity.example",
        oidc_audience="studio",
    )
    token = "fixture-secret-" + "x" * 20000
    key = rate_limit_key(
        request(path, {"Authorization": "Bearer " + token, "X-Tenant-ID": "untrusted" * 10000}),
        settings,
    )
    assert token not in key and "Bearer" not in key and "untrusted" not in key
    assert re.fullmatch(r"/v1/(narrative/|search/lexical):[0-9a-f]{64}:invalid-workspace", key)
    assert len(key) < 120


def test_dev_mode_uses_the_configured_subject_and_ignores_bearer_headers():
    settings = Settings(
        _env_file=None, env="test", auth_mode="dev", dev_auth_subject="fixture-author"
    )
    base = rate_limit_key(request("/v1/query-runs", {}), settings)
    assert (
        rate_limit_key(
            request("/v1/query-runs/other", {"Authorization": "Bearer ignored"}), settings
        )
        == base
    )
    assert (
        rate_limit_key(request("/v1/query-runs", {"X-Dev-User": "another-author"}), settings)
        != base
    )

"""Shared OIDC harness for integration tests.

Lives in a conftest rather than one test module because several suites need a
real authenticated identity: dev auth's fixed principal cannot demonstrate
per-user authorization or audit attribution.
"""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from flint_graph.api.dependencies import get_oidc_token_verifier
from flint_graph.config import Settings, get_settings
from flint_graph.infrastructure.oidc import OIDCTokenVerifier

OIDC_ISSUER = "https://keycloak.example/realms/flintgraph"
OIDC_AUDIENCE = "flintgraph"


def keypair() -> tuple[object, dict[str, object]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    public_jwk["kid"] = "test-key"
    public_jwk["alg"] = "RS256"
    public_jwk["use"] = "sig"
    return private_key, public_jwk


def sign_token(private_key: object, *, subject: str = "user-123") -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": OIDC_ISSUER,
            "sub": subject,
            "aud": OIDC_AUDIENCE,
            "email": f"{subject}@example.com",
            "name": subject,
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )


@pytest.fixture
def oidc_settings_override(client):
    get_settings.cache_clear()

    def override_settings() -> Settings:
        return Settings(
            env="local",
            auth_mode="oidc",
            oidc_issuer=OIDC_ISSUER,
            oidc_audience=OIDC_AUDIENCE,
        )

    from flint_graph.main import app

    app.dependency_overrides[get_settings] = override_settings
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_settings, None)
        get_settings.cache_clear()


@pytest.fixture
def oidc_auth(client, oidc_settings_override):
    private_key, public_jwk = keypair()

    def override_verifier() -> OIDCTokenVerifier:
        return OIDCTokenVerifier(
            issuer=OIDC_ISSUER,
            audience=OIDC_AUDIENCE,
            jwks_loader=lambda: {"keys": [public_jwk]},
        )

    from flint_graph.main import app

    app.dependency_overrides[get_oidc_token_verifier] = override_verifier
    try:
        yield lambda subject="user-123": sign_token(private_key, subject=subject)
    finally:
        app.dependency_overrides.pop(get_oidc_token_verifier, None)

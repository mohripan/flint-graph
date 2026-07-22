from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from flint_graph.domain.errors import UnauthorizedError
from flint_graph.infrastructure.oidc import OIDCTokenVerifier


def _keypair() -> tuple[object, dict[str, object]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    public_jwk["kid"] = "test-key"
    public_jwk["alg"] = "RS256"
    public_jwk["use"] = "sig"
    return private_key, public_jwk


def _token(private_key: object, *, issuer: str, audience: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": issuer,
            "sub": "user-123",
            "aud": audience,
            "email": "analyst@example.com",
            "name": "Analyst User",
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )


async def test_oidc_verifier_accepts_valid_keycloak_style_token() -> None:
    private_key, public_jwk = _keypair()
    verifier = OIDCTokenVerifier(
        issuer="https://keycloak.example/realms/flintgraph",
        audience="flintgraph",
        jwks_loader=lambda: {"keys": [public_jwk]},
    )

    principal = await verifier.verify(
        _token(
            private_key,
            issuer="https://keycloak.example/realms/flintgraph",
            audience="flintgraph",
        )
    )

    assert principal.issuer == "https://keycloak.example/realms/flintgraph"
    assert principal.subject == "user-123"
    assert principal.email == "analyst@example.com"
    assert principal.display_name == "Analyst User"


async def test_oidc_verifier_rejects_wrong_audience() -> None:
    private_key, public_jwk = _keypair()
    verifier = OIDCTokenVerifier(
        issuer="https://keycloak.example/realms/flintgraph",
        audience="flintgraph",
        jwks_loader=lambda: {"keys": [public_jwk]},
    )

    with pytest.raises(UnauthorizedError):
        await verifier.verify(
            _token(
                private_key,
                issuer="https://keycloak.example/realms/flintgraph",
                audience="other-client",
            )
        )

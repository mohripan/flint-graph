"""Shared OIDC harness for integration tests.

Lives in a conftest rather than one test module because several suites need a
real authenticated identity: dev auth's fixed principal cannot demonstrate
per-user authorization or audit attribution.
"""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from flint_graph.api.dependencies import get_oidc_token_verifier
from flint_graph.config import Settings, get_settings
from flint_graph.infrastructure.db.base import Base
from flint_graph.infrastructure.oidc import OIDCTokenVerifier

OIDC_ISSUER = "https://keycloak.example/realms/flintgraph"
OIDC_AUDIENCE = "flintgraph"


@pytest_asyncio.fixture(
    params=["sqlite", "postgres"] if os.getenv("FLINT_GRAPH_PG_INTEGRATION") else ["sqlite"]
)
async def extraction_db_session(request, db_session: AsyncSession) -> AsyncIterator[AsyncSession]:
    if request.param == "sqlite":
        yield db_session
        return
    # Only this fixture's freshly generated schema is created/dropped; public data is untouched.
    schema = f"flint_extraction_test_{uuid4().hex}"
    engine = create_async_engine(os.getenv(
        "FLINT_GRAPH_PG_TEST_URL",
        "postgresql+asyncpg://flint_graph:flint_graph@localhost:55432/flint_graph",
    ))
    async with engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = engine.execution_options(schema_translate_map={None: schema})
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            yield session
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await engine.dispose()


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
            llm_provider="deterministic",
            embedding_provider="deterministic",
            query_answer_provider="deterministic",
            query_support_provider="deterministic",
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

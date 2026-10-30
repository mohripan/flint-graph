"""Shared OIDC harness for integration tests.

Lives in a conftest rather than one test module because several suites need a
real authenticated identity: dev auth's fixed principal cannot demonstrate
per-user authorization or audit attribution.
"""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import jwt
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from flint_graph.api.dependencies import get_oidc_token_verifier, get_session
from flint_graph.config import Settings, get_settings
from flint_graph.infrastructure.db.base import Base
from flint_graph.infrastructure.oidc import OIDCTokenVerifier
from flint_graph.main import app

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
    engine = create_async_engine(
        os.getenv(
            "FLINT_GRAPH_PG_TEST_URL",
            "postgresql+asyncpg://flint_graph:flint_graph@localhost:55432/flint_graph",
        )
    )
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


@pytest_asyncio.fixture(
    params=["sqlite", "postgres"] if os.getenv("FLINT_GRAPH_NARRATIVE_PG_URL") else ["sqlite"]
)
async def narrative_env(client, request, tmp_path) -> AsyncIterator[tuple]:
    # PostgreSQL is opt-in to an explicit owned database; never use the workspace default.
    schema = None
    if request.param == "postgres":
        schema = "narrative_test_" + uuid4().hex
        engine = create_async_engine(os.environ["FLINT_GRAPH_NARRATIVE_PG_URL"])
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        await engine.dispose()
        engine = create_async_engine(
            os.environ["FLINT_GRAPH_NARRATIVE_PG_URL"],
            connect_args={"server_settings": {"search_path": schema + ",public"}},
            hide_parameters=True,
        )
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'narrative.sqlite'}")

        @event.listens_for(engine.sync_engine, "connect")
        def foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        if schema is not None:

            def migrate(sync_connection):
                config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
                config.set_main_option(
                    "script_location", str(Path(__file__).parents[2] / "migrations")
                )
                config.attributes["connection"] = sync_connection
                config.attributes["configure_logger"] = False
                config.attributes["version_table_schema"] = schema
                command.upgrade(config, "head")

            await connection.run_sync(migrate)
        else:
            await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def sessions():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = sessions
    try:
        yield client, factory, request.param
    finally:
        if schema:
            async with engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await engine.dispose()

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable, Mapping
from typing import cast

import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from jwt import PyJWTError
from jwt.algorithms import RSAAlgorithm

from flint_graph.application.services.authz import AuthenticatedPrincipal
from flint_graph.domain.errors import UnauthorizedError

JWKSLoader = Callable[[], Mapping[str, object] | Awaitable[Mapping[str, object]]]


class OIDCTokenVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks_loader: JWKSLoader,
        email_claim: str = "email",
        name_claim: str = "name",
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        self._jwks_loader = jwks_loader
        self._email_claim = email_claim
        self._name_claim = name_claim

    async def verify(self, token: str) -> AuthenticatedPrincipal:
        try:
            header = jwt.get_unverified_header(token)
        except PyJWTError as exc:
            raise UnauthorizedError("The access token header is invalid.") from exc

        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise UnauthorizedError("The access token does not declare a signing key.")

        jwk = await self._load_jwk(kid)
        algorithm = str(jwk.get("alg") or header.get("alg") or "RS256")
        key = cast(RSAPublicKey, RSAAlgorithm.from_jwk(json.dumps(jwk)))

        try:
            claims = jwt.decode(
                token,
                key=key,
                algorithms=[algorithm],
                audience=self._audience,
                issuer=self._issuer,
            )
        except PyJWTError as exc:
            raise UnauthorizedError("The access token is invalid.") from exc

        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise UnauthorizedError("The access token is missing a subject.")

        email = claims.get(self._email_claim)
        name = claims.get(self._name_claim)
        return AuthenticatedPrincipal(
            issuer=self._issuer,
            subject=subject,
            email=email if isinstance(email, str) else None,
            display_name=name if isinstance(name, str) else None,
            claims=dict(claims),
        )

    async def _load_jwk(self, kid: str) -> Mapping[str, object]:
        loaded = self._jwks_loader()
        if inspect.isawaitable(loaded):
            loaded = await loaded
        keys = loaded.get("keys")
        if not isinstance(keys, list):
            raise UnauthorizedError("The OIDC JWKS response is invalid.")
        for key in keys:
            if isinstance(key, Mapping) and key.get("kid") == kid:
                return cast(Mapping[str, object], key)
        raise UnauthorizedError("The access token signing key was not found.")

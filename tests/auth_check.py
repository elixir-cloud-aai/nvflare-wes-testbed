"""Check the WES's own OIDC bearer-token gate: on, off, and a few bad tokens (H5)."""

import os
import sys
import tempfile
import time

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials


class FakeJwkClient:
    """Stands in for `wes.jwk_client()`, so no real issuer or network is needed."""

    def __init__(self, key: rsa.RSAPrivateKey) -> None:
        """Remember the key whose public half every token should verify against.

        Args:
            key: The private key tokens are signed with in this test.
        """
        self.public_key = key.public_key()

    def get_signing_key_from_jwt(self, _token: str) -> "FakeJwkClient":
        """Return this client itself, which also has the `.key` `jwt.decode` wants.

        Args:
            _token: Unused; a real `PyJWKClient` would pick a key by the token's `kid`.

        Returns:
            This client, as its own signing key.
        """
        return self

    @property
    def key(self) -> rsa.RSAPublicKey:
        """The public key to verify a signature against.

        Returns:
            The key.
        """
        return self.public_key


def token(key: rsa.RSAPrivateKey, **claims: object) -> str:
    """Sign a JWT with the given key and claims.

    Args:
        key: The private key to sign with.
        **claims: The claims of the token.

    Returns:
        The signed token.
    """
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test"})


def bearer(value: str) -> HTTPAuthorizationCredentials:
    """Wrap a token as the credentials `wes.authenticated` expects.

    Args:
        value: The token.

    Returns:
        The credentials.
    """
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=value)


def main() -> None:
    """Check the gate with a valid token, no token, a few bad tokens, and no issuer."""
    with tempfile.TemporaryDirectory() as base:
        os.environ["WES_WORKDIR"] = base
        os.environ["WES_OIDC_ISSUER"] = "https://issuer.test/"
        os.environ["WES_OIDC_AUDIENCE"] = "fl-wes"
        sys.path.insert(0, "/app")
        from wes import app as wes

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        wes.jwk_client = lambda: FakeJwkClient(key)

        now = int(time.time())
        good = {"iss": wes.OIDC_ISSUER, "aud": wes.OIDC_AUDIENCE, "sub": "researcher-1", "iat": now, "exp": now + 600}

        def status(credentials: HTTPAuthorizationCredentials | None) -> int:
            try:
                wes.authenticated(credentials)
            except HTTPException as error:
                return error.status_code
            return 200

        checks = {
            "a valid token is accepted": status(bearer(token(key, **good))) == 200,
            "no credentials at all is rejected": status(None) == 401,
            "a token from another key is rejected": status(bearer(token(other_key, **good))) == 401,
            "the wrong audience is rejected": status(bearer(token(key, **{**good, "aud": "someone-else"}))) == 401,
            "the wrong issuer is rejected": status(bearer(token(key, **{**good, "iss": "https://else.test/"}))) == 401,
            "an expired token is rejected": status(bearer(token(key, **{**good, "exp": now - 1}))) == 401,
        }
        wes.OIDC_ISSUER = ""
        checks["no issuer configured lets any caller through"] = wes.authenticated(None) == {}

    for name, passed in checks.items():
        print(f"[{'ok' if passed else 'FAIL'}] {name}")
    sys.exit(0 if all(checks.values()) else 1)


if __name__ == "__main__":
    main()

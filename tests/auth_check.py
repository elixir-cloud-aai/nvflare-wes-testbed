"""Check the WES's OIDC gate, its allow-list, and that a caller only sees its own runs (H5, H22)."""

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
    """Check the gate with a valid token, no token, a few bad tokens, and no issuer configured."""
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
            "a token with no expiry at all is rejected": status(
                bearer(token(key, **{k: v for k, v in good.items() if k != "exp"}))
            )
            == 401,
        }

        def id_status(claims: dict[str, object]) -> int:
            try:
                wes.identity(claims)
            except HTTPException as error:
                return error.status_code
            return 200

        checks["a safe subject is accepted"] = (
            id_status({"sub": "researcher-1", "email": "researcher-1@testbed.invalid"}) == 200
        )
        checks["a missing subject is rejected"] = id_status({}) == 400
        checks["a non-string subject is rejected"] = id_status({"sub": 1, "email": "x@testbed.invalid"}) == 400
        checks["an unsafe email is rejected"] = id_status({"sub": "researcher-1", "email": "not a safe email!"}) == 400
        checks["a non-string email is rejected"] = id_status({"sub": "researcher-1", "email": 1}) == 400
        wes.ALLOWED_SUBS = {"researcher-1"}
        checks["an allowed subject is accepted"] = (
            id_status({"sub": "researcher-1", "email": "researcher-1@testbed.invalid"}) == 200
        )
        checks["a disallowed subject is rejected"] = id_status({"sub": "someone-else"}) == 403
        wes.ALLOWED_SUBS = set()

        def run_status(run_id: str, caller: str) -> int:
            try:
                wes.get_run(run_id, caller)
            except HTTPException as error:
                return error.status_code
            return 200

        # Same email on purpose: ownership is keyed on sub, so a shared or
        # reassigned email must not let another subject see or reach this run
        wes.RUNS["run-a"] = {"state": "COMPLETE", "sub": "researcher-1", "submitter": "researcher-1@testbed.invalid"}
        owner = wes.Identity("researcher-1", "researcher-1@testbed.invalid")
        other = wes.Identity("someone-else", "researcher-1@testbed.invalid")
        runs_as_owner = {r["run_id"] for r in wes.list_runs(owner)["runs"]}
        runs_as_other = {r["run_id"] for r in wes.list_runs(other)["runs"]}
        checks["the owner's run list includes it"] = "run-a" in runs_as_owner
        checks["someone else's run list doesn't, even with the same email"] = "run-a" not in runs_as_other
        checks["the owner can fetch it"] = run_status("run-a", "researcher-1") == 200
        checks["someone else gets 404, not a peek, even with the same email"] = run_status("run-a", "someone-else") == 404

        wes.OIDC_ISSUER = ""
        checks["no issuer configured is itself rejected"] = status(None) == 401

    for name, passed in checks.items():
        print(f"[{'ok' if passed else 'FAIL'}] {name}")
    sys.exit(0 if all(checks.values()) else 1)


if __name__ == "__main__":
    main()

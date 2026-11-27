"""Check who may start runs: the required entitlement, from the token or from userinfo (#70).

In process, with a fake key set and a fake userinfo endpoint, so it needs no
network. Runs in the image (`entitlement-check` in `compose.yaml` and
`tests/compose.hub-test.yaml`, which `tests/hub.sh` runs) or with the WES's
dependencies installed:

    python3 tests/entitlement_check.py
"""

import io
import logging
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import types
import urllib.parse
import uuid
from collections.abc import Callable
from typing import Any

import anyio
import jwt
from auth_check import FakeJwkClient, bearer, token
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

ROOT = pathlib.Path(__file__).resolve().parent.parent
ISSUER = "https://issuer.test/"
USERINFO = "https://issuer.test/userinfo"
CLAIM = "eduperson_entitlement"
# As LS Login names groups: the group that may start runs, and others of the same tree
GROUP = "urn:geant:lifescience-ri.eu:group:elixir:ECP_CLN"
EOC = f"{GROUP}:EOC-Compute#aai.lifescience-ri.eu"
ECP = f"{GROUP}#aai.lifescience-ri.eu"
ECP_ADMIN = f"{GROUP}:ADMIN#aai.lifescience-ri.eu"


class FakeResponse:
    """A userinfo answer, as much of `requests.Response` as the WES reads."""

    def __init__(self, status: int, body: object) -> None:
        """Remember the answer.

        Args:
            status: HTTP status.
            body: The JSON body, or a `ValueError` to raise when it is read, as
                for a body that isn't JSON.
        """
        self.status_code = status
        self.body = body

    def json(self) -> object:
        """Read the body.

        Returns:
            The body.

        Raises:
            ValueError: The body isn't JSON.
        """
        if isinstance(self.body, ValueError):
            raise self.body
        return self.body


class FakeUserinfo:
    """Stands in for `requests` in the WES: answers userinfo requests by token, and counts them."""

    def __init__(self) -> None:
        """Start without answers or calls."""
        self.answers: dict[str, FakeResponse | Exception] = {}
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        """Answer a GET as the issuer's userinfo endpoint would.

        Args:
            url: The URL asked for.
            **kwargs: Headers, timeout and redirects, as `requests.get` takes them.

        Returns:
            The answer set for the bearer token.

        Raises:
            Exception: The answer set for the token, if it is an error, such as
                an issuer out of reach.
        """
        self.calls.append({"url": url, **kwargs})
        value = kwargs.get("headers", {}).get("Authorization", "").removeprefix("Bearer ")
        answer = self.answers.get(value, FakeResponse(401, {"error": "invalid_token"}))
        if isinstance(answer, Exception):
            raise answer
        return answer


def form_call(app: Callable[..., Any], path: str, value: str | None, form: dict[str, str] | None) -> int:
    """Send one request to the WES over ASGI, in process.

    Args:
        app: The application.
        path: The path.
        value: The bearer token, if any.
        form: The form to POST; `None` for a GET.

    Returns:
        The status of the answer.
    """
    body = urllib.parse.urlencode(form).encode() if form is not None else b""
    headers = [(b"content-type", b"application/x-www-form-urlencoded")] if form is not None else []
    if value is not None:
        headers.append((b"authorization", f"Bearer {value}".encode()))
    messages: list[dict[str, Any]] = []
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST" if form is not None else "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [*headers, (b"content-length", str(len(body)).encode())],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    anyio.run(app, scope, receive, send)
    return next(m for m in messages if m["type"] == "http.response.start")["status"]


def refuses_to_start(environ: dict[str, str]) -> str:
    """Import the WES in a process of its own, with settings, as they are read on import.

    Args:
        environ: Settings to add to this process's environment.

    Returns:
        The error output if the import failed, or an empty string if it worked.
    """
    result = subprocess.run(
        [sys.executable, "-c", "from wes import app"],
        cwd=ROOT,
        env={**os.environ, **environ},
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stderr if result.returncode else ""


def main() -> None:
    """Check members, non-members, userinfo, its failures and cache, and the allow-list on top."""
    with tempfile.TemporaryDirectory() as base:
        os.environ["WES_WORKDIR"] = base
        os.environ["WES_OIDC_ISSUER"] = ISSUER
        os.environ["WES_OIDC_AUDIENCE"] = "fl-wes"
        # As an operator would write it: spaces around entries are dropped
        os.environ["WES_OIDC_REQUIRED_ENTITLEMENTS"] = f" {EOC} "
        os.environ.pop("WES_OIDC_ENTITLEMENT_CLAIM", None)
        os.environ["FL_PROBE_RESPONDER"] = "0"
        sys.path.insert(0, str(ROOT))
        from wes import app as wes

        # Everything the WES logs below, to check that no token or entitlement gets there
        log = io.StringIO()
        handler = logging.StreamHandler(log)
        handler.setLevel(logging.DEBUG)
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.DEBUG)

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        wes.jwk_client = lambda: FakeJwkClient(key)
        wes.oidc_discovery = lambda: {"issuer": ISSUER, "jwks_uri": f"{ISSUER}jwk", "userinfo_endpoint": USERINFO}
        userinfo = FakeUserinfo()
        wes.requests = types.SimpleNamespace(get=userinfo.get)

        now = int(time.time())
        tokens_seen: list[str] = []

        def make(sub: str = "researcher-1", lifetime: int = 600, **claims: object) -> tuple[str, dict[str, Any]]:
            # A `jti` of its own: tokens of the same claims and second would otherwise be the same
            value = token(
                key,
                iss=ISSUER,
                aud="fl-wes",
                sub=sub,
                iat=now,
                exp=int(time.time()) + lifetime,
                jti=uuid.uuid4().hex,
                **claims,
            )
            tokens_seen.append(value)
            return value, jwt.decode(value, key.public_key(), algorithms=["RS256"], audience="fl-wes")

        def status(value: str, claims: dict[str, Any]) -> int:
            try:
                caller = wes.identity(claims)
                wes.entitled(bearer(value), claims, caller)
            except HTTPException as error:
                return error.status_code
            return 200

        def member_info(sub: str = "researcher-1", **extra: object) -> FakeResponse:
            return FakeResponse(200, {"sub": sub, CLAIM: [ECP, EOC], **extra})

        checks = {
            "the setting is read, without spaces": wes.REQUIRED_ENTITLEMENTS == frozenset({EOC}),
            "the claim is eduperson_entitlement by default": wes.ENTITLEMENT_CLAIM == CLAIM,
        }

        # From the token
        checks["a member, by the token, may start runs"] = status(*make(**{CLAIM: [ECP, EOC]})) == 200
        checks["a member, by a token with the claim as a string, may start runs"] = status(*make(**{CLAIM: EOC})) == 200
        checks["the parent group alone gets 403"] = status(*make(**{CLAIM: [ECP]})) == 403
        checks["the parent group and its admins get 403"] = status(*make(**{CLAIM: [ECP, ECP_ADMIN]})) == 403
        checks["a subgroup of the group gets 403: exact values only"] = (
            status(*make(**{CLAIM: [f"{GROUP}:EOC-Compute:sub#aai.lifescience-ri.eu"]})) == 403
        )
        checks["the group without its scope gets 403"] = status(*make(**{CLAIM: [f"{GROUP}:EOC-Compute"]})) == 403
        checks["the group in another case gets 403"] = status(*make(**{CLAIM: [EOC.upper()]})) == 403
        checks["an empty claim gets 403"] = status(*make(**{CLAIM: []})) == 403
        checks["a claim of another type gets 403"] = status(*make(**{CLAIM: {"value": EOC}})) == 403
        checks["the value under another claim gets 403"] = status(*make(entitlements=[EOC], **{CLAIM: []})) == 403
        checks["a token that has the claim, but not the group, never asks userinfo"] = userinfo.calls == []

        # From userinfo, when the token lacks the claim
        value, claims = make()
        userinfo.answers[value] = member_info()
        checks["a member, by userinfo, may start runs"] = status(value, claims) == 200
        call = userinfo.calls[-1] if userinfo.calls else {}
        checks["userinfo is asked at the issuer's userinfo endpoint"] = call.get("url") == USERINFO
        checks["userinfo gets the caller's token"] = call.get("headers", {}).get("Authorization") == f"Bearer {value}"
        checks["userinfo follows no redirects"] = call.get("allow_redirects") is False
        checks["userinfo has a timeout"] = isinstance(call.get("timeout"), (int, float)) and call["timeout"] <= 10
        checks["userinfo is cached per token"] = status(value, claims) == 200 and len(userinfo.calls) == 1
        other_value, other_claims = make()
        userinfo.answers[other_value] = FakeResponse(200, {"sub": "researcher-1", CLAIM: [ECP]})
        checks["another token is asked about again, and a non-member by userinfo gets 403"] = (
            status(other_value, other_claims) == 403 and len(userinfo.calls) == 2
        )
        none_value, none_claims = make()
        userinfo.answers[none_value] = FakeResponse(200, {"sub": "researcher-1"})
        checks["no claim in userinfo either gets 403"] = status(none_value, none_claims) == 403

        # Userinfo failures: never allowed
        for case, answer in {
            "userinfo refuses the token": FakeResponse(401, {"error": "invalid_token"}),
            "userinfo fails": FakeResponse(500, {"error": "server_error"}),
            "userinfo redirects": FakeResponse(302, {}),
            "userinfo isn't JSON": FakeResponse(200, ValueError("not JSON")),
            "userinfo isn't an object": FakeResponse(200, [EOC]),
            "userinfo is about another subject": member_info("someone-else"),
            "userinfo has no subject": FakeResponse(200, {CLAIM: [EOC]}),
            "the issuer is out of reach": ConnectionError("unreachable"),
        }.items():
            failing_value, failing_claims = make()
            userinfo.answers[failing_value] = answer
            got = status(failing_value, failing_claims)
            checks[f"{case}: 401, not allowed"] = got == 401
            userinfo.answers[failing_value] = member_info()
            checks[f"{case}: not cached, a retry asks again"] = status(failing_value, failing_claims) == 200

        # The issuer's discovery document
        discovery = wes.oidc_discovery
        for case, document in {
            "names no userinfo endpoint": {"issuer": ISSUER, "jwks_uri": f"{ISSUER}jwk"},
            "names a userinfo endpoint over http": {"userinfo_endpoint": "http://issuer.test/userinfo"},
            "names a userinfo endpoint that isn't a string": {"userinfo_endpoint": ["https://issuer.test/userinfo"]},
        }.items():
            wes.oidc_discovery = lambda document=document: document
            calls = len(userinfo.calls)
            discovery_value, discovery_claims = make()
            userinfo.answers[discovery_value] = member_info()
            checks[f"an issuer that {case}: 401, and no request"] = (
                status(discovery_value, discovery_claims) == 401 and len(userinfo.calls) == calls
            )
        wes.oidc_discovery = discovery

        # The cache lasts no longer than the token
        short_value, short_claims = make(lifetime=1)
        userinfo.answers[short_value] = member_info()
        status(short_value, short_claims)
        calls = len(userinfo.calls)
        time.sleep(1.5)
        userinfo.answers[short_value] = FakeResponse(200, {"sub": "researcher-1", CLAIM: [ECP]})
        checks["a cached answer ends with the token's lifetime"] = (
            status(short_value, short_claims) == 403 and len(userinfo.calls) == calls + 1
        )
        checks["a cached answer lasts at most five minutes"] = wes.USERINFO_CACHE_SECONDS <= 300
        before = len(wes._userinfo_cache)
        for _ in range(wes.USERINFO_CACHE_SIZE + 5):
            many_value, many_claims = make(sub="researcher-many")
            userinfo.answers[many_value] = member_info("researcher-many")
            status(many_value, many_claims)
            del userinfo.answers[many_value]
        checks["the cache has a bound"] = before <= len(wes._userinfo_cache) <= wes.USERINFO_CACHE_SIZE

        # The allow-list on top: both must hold
        wes.ALLOWED_SUBS = {"researcher-1"}
        checks["allow-list and entitlement: a listed member may start runs"] = status(*make(**{CLAIM: [EOC]})) == 200
        checks["allow-list and entitlement: a listed non-member gets 403"] = status(*make(**{CLAIM: [ECP]})) == 403
        checks["allow-list and entitlement: an unlisted member gets 403"] = (
            status(*make(sub="researcher-2", **{CLAIM: [EOC]})) == 403
        )
        wes.ALLOWED_SUBS = set()

        # Without the setting, as before: any caller the issuer vouches for
        wes.REQUIRED_ENTITLEMENTS = frozenset()
        calls = len(userinfo.calls)
        checks["without the setting, a non-member may start runs, as before"] = (
            status(*make(**{CLAIM: [ECP]})) == 200 and status(*make()) == 200 and len(userinfo.calls) == calls
        )
        wes.REQUIRED_ENTITLEMENTS = frozenset({EOC})

        # Over ASGI: only starting runs needs the entitlement; reading stays with the owner
        runs = "/ga4gh/wes/v1/runs"
        bad_run = {"workflow_type": "NONE", "workflow_type_version": "0", "workflow_url": "none"}
        member, _ = make(**{CLAIM: [EOC]})
        outsider, _ = make(sub="outsider-1", **{CLAIM: [ECP, ECP_ADMIN]})
        checks["POST /runs without a token: 401"] = form_call(wes.app, runs, None, bad_run) == 401
        checks["POST /runs as a non-member: 403, before the request is looked at"] = (
            form_call(wes.app, runs, outsider, bad_run) == 403
        )
        checks["POST /runs as a member gets as far as the request"] = form_call(wes.app, runs, member, bad_run) == 400
        wes.RUNS["run-of-outsider"] = {"state": "COMPLETE", "sub": "outsider-1", "submitter": "outsider-1@x.invalid"}
        checks["a non-member still lists runs, its own only"] = form_call(wes.app, runs, outsider, None) == 200 and [
            r["run_id"] for r in wes.list_runs(wes.Identity("outsider-1", "x"))["runs"]
        ] == ["run-of-outsider"]
        checks["a non-member still reads its own run"] = (
            form_call(wes.app, f"{runs}/run-of-outsider/status", outsider, None) == 200
        )
        checks["a member doesn't read another's run"] = (
            form_call(wes.app, f"{runs}/run-of-outsider/status", member, None) == 404
        )

        # What the setting takes
        checks["refuses to start with an empty claim name"] = "WES_OIDC_ENTITLEMENT_CLAIM" in refuses_to_start(
            {"WES_OIDC_REQUIRED_ENTITLEMENTS": EOC, "WES_OIDC_ENTITLEMENT_CLAIM": " "}
        )
        checks["refuses to start with entitlements of empty entries only"] = (
            "WES_OIDC_REQUIRED_ENTITLEMENTS" in refuses_to_start({"WES_OIDC_REQUIRED_ENTITLEMENTS": " , "})
        )
        checks["starts with another claim name"] = (
            refuses_to_start({"WES_OIDC_REQUIRED_ENTITLEMENTS": EOC, "WES_OIDC_ENTITLEMENT_CLAIM": "entitlements"})
            == ""
        )

        logged = log.getvalue()
        checks["something was logged, so the next checks mean something"] = "Auth:" in logged
        checks["no token in the logs"] = not any(value in logged for value in tokens_seen)
        checks["no entitlement in the logs"] = not any(value in logged for value in (EOC, ECP, ECP_ADMIN))

    failed = 0
    for name, passed in checks.items():
        print(f"[{'ok' if passed else 'FAIL'}] {name}")
        failed += not passed
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

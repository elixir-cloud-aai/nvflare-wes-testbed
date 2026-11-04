"""A fake OpenID Connect identity provider, for proTES in the testbed (hack H10).

Hands access tokens to anyone who asks, at `GET /oidc/token?sub=<user>`. Cut down
from the fake TES of the smoke test of proTES (Apache-2.0).
"""

import json
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

ISSUER = "http://fake-idp:8080/oidc/"
AUDIENCE = "fl-wes"
GROUP = "fl-users"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class Handler(BaseHTTPRequestHandler):
    """Serves discovery, keys, user info and tokens."""

    def _send(self, status: HTTPStatus, body: object) -> None:
        """Send a JSON response.

        Args:
            status: Status of the response.
            body: Body of the response.
        """
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        """Serve the endpoints of the identity provider."""
        url = urlsplit(self.path)
        if url.path == "/oidc/.well-known/openid-configuration":
            self._send(
                HTTPStatus.OK,
                {"issuer": ISSUER, "jwks_uri": f"{ISSUER}jwk", "userinfo_endpoint": f"{ISSUER}userinfo"},
            )
        elif url.path == "/oidc/jwk":
            key = jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key(), as_dict=True)
            self._send(HTTPStatus.OK, {"keys": [{**key, "kid": "fake", "use": "sig"}]})
        elif url.path == "/oidc/userinfo":
            token = (self.headers.get("Authorization") or "").removeprefix("Bearer ")
            try:
                claims = jwt.decode(token, KEY.public_key(), algorithms=["RS256"], audience=AUDIENCE)
            except jwt.InvalidTokenError:
                self._send(HTTPStatus.UNAUTHORIZED, {"error": "invalid_token"})
                return
            self._send(HTTPStatus.OK, {"sub": claims["sub"], "groups": [GROUP]})
        elif url.path == "/oidc/token":
            sub = parse_qs(url.query).get("sub", ["fl-wes"])[0]
            now = int(time.time())
            token = jwt.encode(
                {"iss": ISSUER, "aud": AUDIENCE, "sub": sub, "iat": now, "exp": now + 600},
                KEY,
                algorithm="RS256",
                headers={"kid": "fake", "typ": "at+jwt"},
            )
            self._send(HTTPStatus.OK, {"access_token": token})
        else:
            self._send(HTTPStatus.NOT_FOUND, {"error": "not_found"})


if __name__ == "__main__":
    ThreadingHTTPServer(("", 8080), Handler).serve_forever()

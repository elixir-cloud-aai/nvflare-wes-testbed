"""Unit tests of `wes/tokens.py`, with a mock OAuth 2.0 provider on this host. No other network needed.

Usage: python3 tests/tokens_test.py
"""

import base64
import contextlib
import http.server
import json
import pathlib
import sys
import tempfile
import threading
import unittest
import urllib.parse
from collections.abc import Iterator
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from wes import tokens

CLIENT_ID = "hub-client"
# Decoys: none of these may show up in a message
CLIENT_SECRET = "decoy-client-secret"
REFRESH_TOKEN = "decoy-refresh-token-0"
ENVIRON = {"SITE_CLIENT_SECRET": CLIENT_SECRET, "SITE_REFRESH_TOKEN": REFRESH_TOKEN}


class Provider:
    """What the mock provider answers, and what it was sent."""

    def __init__(self) -> None:
        """Start with a provider that works."""
        self.issuer = ""
        self.requests: list[dict[str, Any]] = []
        self.expires_in: Any = 3600
        self.status = 200
        self.error = ""
        self.token_type = "Bearer"
        self.rotate = False
        self.redirect = False
        self.garbage = b""
        self.override: dict[str, Any] = {}
        self.discovery: dict[str, Any] | None = None


class Handler(http.server.BaseHTTPRequestHandler):
    """Serves OpenID Connect discovery and a token endpoint, as `Provider` says."""

    provider: Provider

    def reply(self, status: int, body: Any, headers: dict[str, str] | None = None) -> None:
        """Send a JSON response.

        Args:
            status: Its status.
            body: Its body.
            headers: More headers.
        """
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        """Answer discovery."""
        provider = self.provider
        if self.path == "/realm/.well-known/openid-configuration":
            discovery = provider.discovery or {"issuer": provider.issuer, "token_endpoint": f"{provider.issuer}/token"}
            self.reply(200, discovery)
        else:
            self.reply(404, {"error": "not_found"})

    def do_POST(self) -> None:
        """Answer the token endpoint, and record what it was sent."""
        provider = self.provider
        length = int(self.headers.get("Content-Length", "0"))
        form = dict(urllib.parse.parse_qsl(self.rfile.read(length).decode()))
        provider.requests.append({"path": self.path, "form": form, "authorization": self.headers.get("Authorization")})
        if provider.garbage:
            self.wfile.write(provider.garbage)
            self.close_connection = True
            return
        if self.path == "/elsewhere":
            self.reply(200, {"access_token": "decoy-elsewhere", "token_type": "Bearer"})
            return
        if provider.redirect:
            self.reply(302, {}, {"Location": f"{provider.issuer.removesuffix('/realm')}/elsewhere"})
            return
        if provider.status != 200:
            self.reply(provider.status, {"error": provider.error, "error_description": f"bad {CLIENT_SECRET}"})
            return
        number = len(provider.requests)
        body: dict[str, Any] = {"access_token": f"access-{number}", "token_type": provider.token_type}
        if provider.expires_in is not None:
            body["expires_in"] = provider.expires_in
        if provider.rotate:
            body["refresh_token"] = f"decoy-refresh-token-{number}"
        self.reply(200, {**body, **provider.override})

    def log_message(self, *args: Any) -> None:
        """Log nothing.

        Args:
            *args: Unused.
        """


@contextlib.contextmanager
def provider() -> Iterator[Provider]:
    """Run the mock provider on a free port of this host.

    Yields:
        What it answers, with its issuer.
    """
    state = Provider()
    handler = type("BoundHandler", (Handler,), {"provider": state})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    state.issuer = f"http://127.0.0.1:{server.server_address[1]}/realm"
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()


class Clock:
    """A clock that a test moves on."""

    def __init__(self) -> None:
        """Start at 1000 seconds."""
        self.now = 1000.0

    def __call__(self) -> float:
        """Tell the time.

        Returns:
            The time, in seconds.
        """
        return self.now


def oauth(issuer: str, **config: str) -> dict[str, str]:
    """Build the `oauth` of a site, with the refresh token grant by default.

    Args:
        issuer: The issuer.
        **config: Keys to set or override.

    Returns:
        The configuration.
    """
    return {
        "issuer": issuer,
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "refresh_token_env": "SITE_REFRESH_TOKEN",
        **config,
    }


def basic(client_id: str, secret: str) -> str:
    """Build the header of `client_secret_basic`.

    Args:
        client_id: The client ID.
        secret: The client secret.

    Returns:
        The header's value.
    """
    return "Basic " + base64.b64encode(f"{client_id}:{secret}".encode()).decode()


class SourcesTest(unittest.TestCase):
    """Which source a site gets, and what's refused."""

    def assert_refused(self, config: dict[str, Any], message: str) -> None:
        """Check that a site's entry is refused, without secrets in the message.

        Args:
            config: The entry.
            message: Part of the expected message.
        """
        with self.assertRaises(ValueError) as caught:
            tokens.from_site("site-1", config, ENVIRON)
        self.assertIn(message, str(caught.exception))
        self.assertNotIn("decoy", str(caught.exception))

    def test_no_token(self) -> None:
        """A site without a token gets no source."""
        self.assertIsNone(tokens.from_site("site-1", {"tes": "https://tes"}, ENVIRON))

    def test_static_token(self) -> None:
        """`token` works as before."""
        source = tokens.from_site("site-1", {"token": "decoy-token-1"}, ENVIRON)
        assert source is not None
        self.assertEqual(source.token(), "decoy-token-1")
        self.assertFalse(source.renewable)

    def test_refusals(self) -> None:
        """Entries that can't work are refused, with messages that hold no secrets."""
        issuer = "https://login.example.org/realm"
        self.assert_refused({"token": "decoy-token\n"}, "can't go into a header")
        self.assert_refused({"token": "decoy-token", "token_file": "/x"}, "more than one token source")
        self.assert_refused({"token_file": "relative/path"}, "absolute path")
        self.assert_refused({"token_file": "/nonexistent/decoy"}, "Can't read")
        self.assert_refused({"oauth": "decoy"}, "must be an object")
        self.assert_refused({"oauth": oauth(issuer, client_secret="decoy-inline")}, "unknown keys")
        self.assert_refused({"oauth": oauth("http://login.example.org/realm")}, "https")
        self.assert_refused({"oauth": oauth(issuer, token_endpoint=f"{issuer}/token")}, "either issuer")
        self.assert_refused({"oauth": oauth(issuer, grant_type="password")}, "grant_type")
        self.assert_refused({"oauth": oauth(issuer, client_id="")}, "client_id")
        self.assert_refused({"oauth": oauth(issuer, refresh_token_env="UNSET_VARIABLE")}, "UNSET_VARIABLE")
        self.assert_refused({"oauth": oauth(issuer, grant_type="client_credentials")}, "client_secret_env")

    def test_http_only_on_this_host(self) -> None:
        """Plain HTTP only goes to this host, for tests: never over a network."""
        for url in ("http://127.0.0.1:1/x", "http://localhost/x", "https://login.example.org/x"):
            tokens.check_url(url, "url")
        for url in (
            "http://login.example.org/x",
            "http://127.0.0.1.example.org/x",
            "ftp://localhost/x",
            "https://",
            "https://login.example.org:99999/x",
            "https://login.example.org:port/x",
        ):
            with self.assertRaises(ValueError):
                tokens.check_url(url, "url")


class FileTokenTest(unittest.TestCase):
    """`token_file`: read before each request."""

    def test_read_on_each_call(self) -> None:
        """A new token in the file is used without a restart."""
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "token"
            path.write_text("decoy-file-token-1\n")
            source = tokens.from_site("site-1", {"token_file": str(path)}, ENVIRON)
            assert source is not None
            self.assertEqual(source.token(), "decoy-file-token-1")
            path.write_text("decoy-file-token-2")
            self.assertEqual(source.token(), "decoy-file-token-2")
            path.write_text("")
            with self.assertRaises(tokens.TokenError) as caught:
                source.token()
            path.write_text("decoy bad token")
            with self.assertRaises(tokens.TokenError) as bad:
                source.token()
            path.unlink()
            with self.assertRaises(tokens.TokenError) as gone:
                source.token()
        for error in (caught, bad, gone):
            self.assertIn("site-1", str(error.exception))
            self.assertNotIn("decoy", str(error.exception))


class OAuthTokenTest(unittest.TestCase):
    """`oauth`: tokens from a token endpoint, cached and renewed."""

    def source(self, config: dict[str, str], clock: Clock | None = None) -> tokens.OAuthToken:
        """Build an `oauth` source.

        Args:
            config: The site's `oauth`.
            clock: The clock, by default one that stands still.

        Returns:
            The source.
        """
        return tokens.OAuthToken("site-1", config, ENVIRON, clock=clock or Clock())

    def test_refresh_token(self) -> None:
        """The refresh token grant, by discovery, as a public client."""
        with provider() as state:
            source = self.source(oauth(state.issuer, scope="openid offline_access"))
            self.assertEqual(source.token(), "access-1")
            self.assertEqual(state.requests[0]["path"], "/realm/token")
            self.assertEqual(
                state.requests[0]["form"],
                {
                    "grant_type": "refresh_token",
                    "refresh_token": REFRESH_TOKEN,
                    "client_id": CLIENT_ID,
                    "scope": "openid offline_access",
                },
            )
            self.assertIsNone(state.requests[0]["authorization"])

    def test_client_credentials(self) -> None:
        """The client credentials grant, at a configured endpoint, with `client_secret_basic`."""
        with provider() as state:
            config = {
                "token_endpoint": f"{state.issuer}/token",
                "grant_type": "client_credentials",
                "client_id": CLIENT_ID,
                "client_secret_env": "SITE_CLIENT_SECRET",
            }
            self.assertEqual(self.source(config).token(), "access-1")
            self.assertEqual(state.requests[0]["form"], {"grant_type": "client_credentials"})
            self.assertEqual(state.requests[0]["authorization"], basic(CLIENT_ID, CLIENT_SECRET))

    def test_renewed_before_expiry(self) -> None:
        """A run longer than a token's lifetime gets a new one in time, and the cached one until then."""
        clock = Clock()
        with provider() as state:
            state.expires_in = 600
            source = self.source(oauth(state.issuer), clock)
            self.assertEqual(source.token(), "access-1")
            clock.now += 539
            self.assertEqual(source.token(), "access-1")
            clock.now += 1
            self.assertEqual(source.token(), "access-2")
            # Many hours, many lifetimes
            for hour in range(12):
                clock.now += 3600
                source.token()
            self.assertEqual(len(state.requests), 14)

    def test_short_lifetime(self) -> None:
        """A token that lives less than twice the margin is renewed at half its lifetime."""
        clock = Clock()
        with provider() as state:
            state.expires_in = 60
            source = self.source(oauth(state.issuer), clock)
            source.token()
            clock.now += 29
            self.assertEqual(source.token(), "access-1")
            clock.now += 1
            self.assertEqual(source.token(), "access-2")

    def test_no_lifetime(self) -> None:
        """Without `expires_in`, or with a bad one, a token counts as short-lived."""
        for expires_in in (None, "3600", -1, True, float("nan"), float("inf")):
            clock = Clock()
            with provider() as state:
                state.expires_in = expires_in
                source = self.source(oauth(state.issuer), clock)
                source.token()
                clock.now += tokens.DEFAULT_LIFETIME - tokens.RENEW_BEFORE
                self.assertEqual(source.token(), "access-2", expires_in)

    def test_longest_lifetime(self) -> None:
        """A lifetime of years is believed for a day at most."""
        clock = Clock()
        with provider() as state:
            # Too large for a float, too
            state.expires_in = 10**400
            source = self.source(oauth(state.issuer), clock)
            source.token()
            clock.now += tokens.MAX_LIFETIME - tokens.RENEW_BEFORE
            self.assertEqual(source.token(), "access-2")

    def test_rotated_refresh_token(self) -> None:
        """A new refresh token in a response is used for the next renewal."""
        clock = Clock()
        with provider() as state:
            state.rotate = True
            source = self.source(oauth(state.issuer), clock)
            refused = source.token()
            clock.now += tokens.MIN_RENEW_INTERVAL
            source.invalidate(refused)
            source.token()
            self.assertEqual(state.requests[1]["form"]["refresh_token"], "decoy-refresh-token-1")

    def test_invalidate(self) -> None:
        """A refused token is forgotten, and a new one requested."""
        clock = Clock()
        with provider() as state:
            source = self.source(oauth(state.issuer), clock)
            self.assertEqual(source.token(), "access-1")
            self.assertEqual(source.token(), "access-1")
            clock.now += tokens.MIN_RENEW_INTERVAL
            source.invalidate("access-1")
            self.assertEqual(source.token(), "access-2")
            self.assertTrue(source.renewable)

    def test_invalidate_stale(self) -> None:
        """A refusal of a token renewed meanwhile keeps the new one: one renewal, not one per request."""
        clock = Clock()
        with provider() as state:
            source = self.source(oauth(state.issuer), clock)
            source.token()
            clock.now += tokens.MIN_RENEW_INTERVAL
            source.invalidate("access-1")
            self.assertEqual(source.token(), "access-2")
            clock.now += tokens.MIN_RENEW_INTERVAL
            source.invalidate("access-1")
            self.assertEqual(source.token(), "access-2")
            self.assertEqual(len(state.requests), 2)

    def test_invalidate_fresh(self) -> None:
        """A TES that refuses every token doesn't make each request a renewal."""
        clock = Clock()
        with provider() as state:
            source = self.source(oauth(state.issuer), clock)
            source.invalidate(source.token())
            self.assertEqual(source.token(), "access-1")
            clock.now += tokens.MIN_RENEW_INTERVAL
            source.invalidate(source.token())
            self.assertEqual(source.token(), "access-2")

    def test_failed_renewal(self) -> None:
        """A failed renewal keeps a token that's still valid, and waits before it asks again."""
        clock = Clock()
        with provider() as state:
            state.expires_in = 600
            source = self.source(oauth(state.issuer), clock)
            source.token()
            state.status, state.error = 503, "temporarily_unavailable"
            clock.now += 550
            self.assertEqual(source.token(), "access-1")
            self.assertEqual(source.token(), "access-1")
            self.assertEqual(len(state.requests), 2)
            clock.now += tokens.RETRY_AFTER
            self.assertEqual(source.token(), "access-1")
            self.assertEqual(len(state.requests), 3)
            # Expired now, and the provider is still down
            clock.now += 600
            with self.assertRaises(tokens.TokenError):
                source.token()
            with self.assertRaises(tokens.TokenError) as waiting:
                source.token()
            self.assertIn("last renewal failed", str(waiting.exception))
            self.assertEqual(len(state.requests), 4)
            state.status = 200
            clock.now += tokens.RETRY_AFTER
            self.assertEqual(source.token(), "access-5")

    def test_odd_access_tokens(self) -> None:
        """An access token that isn't a string is refused, not turned into one."""
        for access_token in (None, 12, True, ["decoy"]):
            with provider() as state:
                state.override = {"access_token": access_token}
                self.assert_fails(state, "no access token")

    def test_rotation_kept_on_bad_response(self) -> None:
        """A rotated refresh token is kept even if the rest of the response is unusable."""
        with provider() as state:
            state.rotate = True
            state.token_type = "mac"
            clock = Clock()
            source = self.source(oauth(state.issuer), clock)
            with self.assertRaises(tokens.TokenError):
                source.token()
            state.token_type = "Bearer"
            clock.now += tokens.RETRY_AFTER
            source.token()
            self.assertEqual(state.requests[1]["form"]["refresh_token"], "decoy-refresh-token-1")

    def test_truncated_error(self) -> None:
        """An error response cut short fails as a `TokenError`."""
        with provider() as state:
            state.garbage = b"HTTP/1.1 400 Bad Request\r\nContent-Length: 100\r\n\r\n{"
            self.assert_fails(state, "site-1")

    def test_no_url_in_messages(self) -> None:
        """Messages name no URL, which could hold credentials."""
        source = self.source(oauth("http://user:decoy-password@127.0.0.1:1/realm"))
        with self.assertRaises(tokens.TokenError) as caught:
            source.token()
        self.assertNotIn("decoy", str(caught.exception))
        self.assertNotIn("127.0.0.1", str(caught.exception))

    def test_slow_failure_past_expiry(self) -> None:
        """A renewal that fails after the cached token expired doesn't return the expired token."""
        clock = Clock()

        class Slow:
            """A token endpoint that answers once, then times out."""

            def get_json(self, url: str) -> tuple[int, Any]:
                """Never called: the endpoint is configured.

                Args:
                    url: Unused.

                Raises:
                    AssertionError: Always.
                """
                raise AssertionError("no discovery")

            def post_form(self, url: str, form: Any, headers: Any) -> tuple[int, Any]:
                """Answer with a token that lives 100 s, then time out.

                Args:
                    url: Unused.
                    form: Unused.
                    headers: Unused.

                Returns:
                    The first token.

                Raises:
                    TokenError: After the first time, after the timeout.
                """
                if clock.now == 1000.0:
                    return 200, {"access_token": "access-1", "token_type": "Bearer", "expires_in": 100}
                clock.now += tokens.TIMEOUT
                raise tokens.TokenError("No response")

        config = {**oauth("https://login.example.org/realm"), "token_endpoint": "https://login.example.org/token"}
        del config["issuer"]
        source = tokens.OAuthToken("site-1", config, ENVIRON, http=Slow(), clock=clock)
        self.assertEqual(source.token(), "access-1")
        clock.now = 1095.0
        with self.assertRaises(tokens.TokenError):
            source.token()

    def test_slow_failure(self) -> None:
        """The wait after a failed renewal counts from the failure, so a provider that times out isn't asked each call."""
        clock = Clock()

        class Hanging:
            """A provider that answers nothing, after the timeout."""

            calls = 0

            def get_json(self, url: str) -> tuple[int, Any]:
                """Time out.

                Args:
                    url: Unused.

                Raises:
                    TokenError: Always, after the timeout.
                """
                Hanging.calls += 1
                clock.now += tokens.TIMEOUT
                raise tokens.TokenError("No response")

            def post_form(self, url: str, form: Any, headers: Any) -> tuple[int, Any]:
                """Never called: discovery fails first.

                Args:
                    url: Unused.
                    form: Unused.
                    headers: Unused.

                Raises:
                    AssertionError: Always.
                """
                raise AssertionError("no discovery, no token endpoint")

        source = tokens.OAuthToken(
            "site-1", oauth("https://login.example.org/realm"), ENVIRON, http=Hanging(), clock=clock
        )
        for _ in range(3):
            with self.assertRaises(tokens.TokenError):
                source.token()
            clock.now += 2
        self.assertEqual(Hanging.calls, 1)

    def test_malformed_replies(self) -> None:
        """A reply that isn't HTTP, or JSON nested too deep, fails as a `TokenError`."""
        for garbage in (b"GARBAGE\r\n\r\n", b"HTTP/1.1 200 OK\r\nContent-Length: 200000\r\n\r\n" + b"[" * 200000):
            with provider() as state:
                state.garbage = garbage
                with self.assertRaises(tokens.TokenError, msg=garbage[:20]):
                    self.source(oauth(state.issuer)).token()

    def test_discovery_once(self) -> None:
        """Discovery happens once, not for each token."""
        clock = Clock()
        with provider() as state:
            source = self.source(oauth(state.issuer), clock)
            refused = source.token()
            clock.now += tokens.MIN_RENEW_INTERVAL
            source.invalidate(refused)
            state.discovery = {"issuer": state.issuer, "token_endpoint": "http://example.org/token"}
            self.assertEqual(source.token(), "access-2")

    def assert_fails(self, state: Provider, message: str) -> None:
        """Check that getting a token fails, without secrets in the message.

        Args:
            state: The provider, set up to fail.
            message: Part of the expected message.
        """
        with self.assertRaises(tokens.TokenError) as caught:
            self.source(oauth(state.issuer)).token()
        self.assertIn(message, str(caught.exception))
        self.assertIn("site-1", str(caught.exception))
        self.assertNotIn("decoy", str(caught.exception))

    def test_failures(self) -> None:
        """What the provider gets wrong fails the token, with messages that hold no secrets."""
        with provider() as state:
            state.status, state.error = 400, "invalid_grant"
            self.assert_fails(state, "status 400 (invalid_grant)")
            state.error = f"not a code {REFRESH_TOKEN}"
            self.assert_fails(state, "status 400")
            state.status = 200
            state.token_type = "mac"
            self.assert_fails(state, "no bearer token")
            state.token_type = "Bearer"
            state.discovery = {"issuer": "https://login.example.org/realm", "token_endpoint": f"{state.issuer}/token"}
            self.assert_fails(state, "another issuer")
            state.discovery = {"issuer": state.issuer, "token_endpoint": "http://login.example.org/token"}
            self.assert_fails(state, "https")
            state.discovery = {"issuer": state.issuer}
            self.assert_fails(state, "no token endpoint")
        # The provider is gone now
        self.assert_fails(state, "No response")

    def test_no_redirect(self) -> None:
        """A redirect isn't followed, so credentials stay with the token endpoint."""
        with provider() as state:
            state.redirect = True
            config = {
                "token_endpoint": f"{state.issuer}/token",
                "grant_type": "client_credentials",
                "client_id": CLIENT_ID,
                "client_secret_env": "SITE_CLIENT_SECRET",
            }
            with self.assertRaises(tokens.TokenError) as caught:
                self.source(config).token()
            self.assertIn("status 302", str(caught.exception))
            self.assertEqual([request["path"] for request in state.requests], ["/realm/token"])

    def test_threads(self) -> None:
        """Requests at once share one token."""
        with provider() as state:
            source = self.source(oauth(state.issuer))
            threads = [threading.Thread(target=source.token) for _ in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(len(state.requests), 1)


if __name__ == "__main__":
    unittest.main()

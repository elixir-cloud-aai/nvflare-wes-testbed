"""Access tokens for the TES of the sites, read or renewed when they are needed.

A site of the sites file names at most one source for its token:

- `token`: one token, as it is, for as long as the hub runs;
- `token_file`: a file that holds the token, read before each request, so that
  whoever renews it (a mounted Secret, a script) needs no restart of the hub;
- `oauth`: tokens from the token endpoint of an OAuth 2.0 provider, with the
  refresh token or the client credentials grant, cached and renewed before
  they expire.

Secrets come in only at run time: the `oauth` source names the environment
variables that hold the client secret and the refresh token, and takes the
token endpoint from the provider's OpenID Connect discovery. No message of this
module holds a token or a secret. Only the standard library, so that the tests
need nothing else.
"""

import base64
import http.client
import json
import math
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any, Protocol

# A token goes into a header as it is, so only visible ASCII
TOKEN_PATTERN = re.compile(r"[\x21-\x7e]+")
# Renewed this many seconds before it expires, or at half its lifetime if that's shorter
RENEW_BEFORE = 60.0
# Lifetime assumed for a token whose response doesn't say (`expires_in`), and the longest believed
DEFAULT_LIFETIME = 300.0
MAX_LIFETIME = 86400.0
# Seconds before the provider is asked again after a failed renewal
RETRY_AFTER = 10.0
# A refused token is renewed only if it is at least this many seconds old
MIN_RENEW_INTERVAL = 30.0
TIMEOUT = 10.0
MAX_RESPONSE_SIZE = 1 << 20
GRANT_TYPES = ("refresh_token", "client_credentials")
OAUTH_KEYS = {"issuer", "token_endpoint", "grant_type", "client_id", "client_secret_env", "refresh_token_env", "scope"}
LOOPBACK = {"127.0.0.1", "::1", "localhost"}
# What of an error response may go into a message: the error code of RFC 6749
ERROR_CODE = re.compile(r"[a-z_]{1,64}")


class TokenError(Exception):
    """A token couldn't be had. The message holds no token or secret."""


class Http(Protocol):
    """What the `oauth` source needs of HTTP, so that a test can fake it."""

    def get_json(self, url: str) -> tuple[int, Any]:
        """Get a JSON document.

        Args:
            url: Its URL.

        Returns:
            The status code, and the parsed body, or `None` if it isn't JSON.
        """
        ...

    def post_form(self, url: str, form: Mapping[str, str], headers: Mapping[str, str]) -> tuple[int, Any]:
        """Post a form, and get JSON back.

        Args:
            url: The URL.
            form: The fields, sent as `application/x-www-form-urlencoded`.
            headers: More headers, e.g. `Authorization`.

        Returns:
            The status code, and the parsed body, or `None` if it isn't JSON.
        """
        ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Follows no redirect: one could take credentials to another host."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        """Refuse to redirect: with no new request, the redirect comes back as the response.

        Args:
            *args: Unused.
            **kwargs: Unused.
        """


class UrllibHttp:
    """`Http` over `urllib`, without redirects, with a timeout and a size limit."""

    def __init__(self, timeout: float = TIMEOUT) -> None:
        """Build the client.

        Args:
            timeout: Seconds to wait for a response.
        """
        self._opener = urllib.request.build_opener(_NoRedirect)
        self._timeout = timeout

    def _send(self, request: urllib.request.Request) -> tuple[int, Any]:
        """Send a request, and parse the response as JSON.

        Args:
            request: The request.

        Returns:
            The status code, and the parsed body, or `None` if it isn't JSON.

        Raises:
            TokenError: There's no response, e.g., the host is out of reach.
        """
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                status, body = response.status, response.read(MAX_RESPONSE_SIZE)
        except urllib.error.HTTPError as error:
            status, body = error.code, error.read(MAX_RESPONSE_SIZE)
        except (urllib.error.URLError, http.client.HTTPException, OSError) as error:
            raise TokenError(f"No response from {request.full_url}: {type(error).__name__}") from None
        try:
            return status, json.loads(body)
        except (ValueError, RecursionError):
            return status, None

    def get_json(self, url: str) -> tuple[int, Any]:
        """Get a JSON document.

        Args:
            url: Its URL.

        Returns:
            The status code, and the parsed body, or `None` if it isn't JSON.
        """
        return self._send(urllib.request.Request(url, headers={"Accept": "application/json"}))

    def post_form(self, url: str, form: Mapping[str, str], headers: Mapping[str, str]) -> tuple[int, Any]:
        """Post a form, and get JSON back.

        Args:
            url: The URL.
            form: The fields, sent as `application/x-www-form-urlencoded`.
            headers: More headers, e.g. `Authorization`.

        Returns:
            The status code, and the parsed body, or `None` if it isn't JSON.
        """
        data = urllib.parse.urlencode(form).encode()
        all_headers = {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded", **headers}
        return self._send(urllib.request.Request(url, data=data, headers=all_headers, method="POST"))


def check_url(url: str, what: str) -> None:
    """Check that a URL may carry credentials: `https`, or `http` to this host only.

    Args:
        url: The URL.
        what: What it is, for the message.

    Raises:
        ValueError: It's neither.
    """
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "https" and parts.hostname:
        return
    if parts.scheme == "http" and parts.hostname in LOOPBACK:
        return
    raise ValueError(f"{what} must be an https URL")


def check_token(token: str, what: str) -> str:
    """Check that a token can go into a header.

    Args:
        token: The token.
        what: What it is, for the message, which doesn't hold the token.

    Returns:
        The token.

    Raises:
        TokenError: It can't.
    """
    if not TOKEN_PATTERN.fullmatch(token):
        raise TokenError(f"{what} has characters that can't go into a header, or is empty")
    return token


class TokenSource(Protocol):
    """Where the token of a site comes from."""

    #: Whether `invalidate` can lead to another token, so that a `401` is worth a retry
    renewable: bool

    def token(self) -> str:
        """Get a token that is valid now.

        Returns:
            The token.
        """
        ...

    def invalidate(self, refused: str) -> None:
        """Forget the cached token if it's the one the TES refused.

        Args:
            refused: The token the TES refused. If another request renewed it
                meanwhile, the new one stays.
        """
        ...


class StaticToken:
    """One token, as it is, from the sites file."""

    renewable = False

    def __init__(self, site: str, token: str) -> None:
        """Check the token.

        Args:
            site: Name of the site.
            token: The token.

        Raises:
            ValueError: It can't go into a header. The message doesn't hold it.
        """
        try:
            self._token = check_token(token, f"The token of site {site}")
        except TokenError as error:
            raise ValueError(str(error)) from None

    def token(self) -> str:
        """Get the token.

        Returns:
            The token.
        """
        return self._token

    def invalidate(self, refused: str) -> None:
        """Do nothing: there's no other token.

        Args:
            refused: Unused.
        """


class FileToken:
    """A token in a file, read before each request."""

    renewable = True

    def __init__(self, site: str, path: str) -> None:
        """Check that the file can be read.

        Args:
            site: Name of the site.
            path: Absolute path of the file.

        Raises:
            ValueError: The path isn't absolute, or the file holds no token
                that can go into a header.
        """
        if not os.path.isabs(path):
            raise ValueError(f"The token file of site {site} must be an absolute path")
        self._site = site
        self._path = path
        try:
            self.token()
        except TokenError as error:
            raise ValueError(str(error)) from None

    def token(self) -> str:
        """Read the token, without surrounding white space.

        Returns:
            The token.

        Raises:
            TokenError: The file can't be read, or holds no token that can go
                into a header.
        """
        try:
            with open(self._path, encoding="utf-8") as file:
                token = file.read(MAX_RESPONSE_SIZE).strip()
        except (OSError, UnicodeDecodeError) as error:
            raise TokenError(f"Can't read the token file of site {self._site}: {type(error).__name__}") from None
        return check_token(token, f"The token file of site {self._site}")

    def invalidate(self, refused: str) -> None:
        """Do nothing: the file is read anew anyway.

        Args:
            refused: Unused.
        """


class OAuthToken:
    """Tokens from an OAuth 2.0 token endpoint, cached and renewed before they expire."""

    renewable = True

    def __init__(
        self,
        site: str,
        config: Mapping[str, Any],
        environ: Mapping[str, str],
        http: Http | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Check the configuration, and take the secrets from the environment.

        Args:
            site: Name of the site.
            config: The site's `oauth`: `issuer` (for OpenID Connect discovery)
                or `token_endpoint`, `grant_type` (`refresh_token` or
                `client_credentials`), `client_id`, and the names of the
                environment variables with the secrets, `client_secret_env`
                (required for `client_credentials`) and `refresh_token_env`
                (required for `refresh_token`); optionally `scope`.
            environ: The environment to take the secrets from.
            http: How to reach the provider.
            clock: Seconds, monotonic.

        Raises:
            ValueError: The configuration is incomplete or unknown, a URL is
                not `https`, or a variable it names isn't set. The message
                names variables, never their values.
        """
        what = f"The oauth of site {site}"
        if not isinstance(config, Mapping):
            raise ValueError(f"{what} must be an object")  # noqa: TRY004 - all errors of the sites file are ValueError
        if unknown := sorted(set(config) - OAUTH_KEYS):
            raise ValueError(f"{what} has unknown keys: {unknown}")
        if not all(isinstance(value, str) for value in config.values()):
            raise ValueError(f"{what} must have strings as values")
        if ("issuer" in config) == ("token_endpoint" in config):
            raise ValueError(f"{what} needs either issuer or token_endpoint")
        for key in ("issuer", "token_endpoint"):
            if key in config:
                check_url(config[key], f"{key} of site {site}")
        grant = config.get("grant_type", "")
        if grant not in GRANT_TYPES:
            raise ValueError(f"{what} needs grant_type, one of {list(GRANT_TYPES)}")
        if not config.get("client_id"):
            raise ValueError(f"{what} needs client_id")
        needed = ["client_secret_env"] if grant == "client_credentials" else ["refresh_token_env"]
        for key in needed:
            if key not in config:
                raise ValueError(f"{what} needs {key} for grant_type {grant}")
        secrets: dict[str, str] = {}
        for key in ("client_secret_env", "refresh_token_env"):
            if key in config:
                name = config[key]
                if not environ.get(name):
                    raise ValueError(f"{what} names the variable {name} in {key}, which isn't set")
                secrets[key] = environ[name]
        self._site = site
        self._issuer = config.get("issuer", "")
        self._endpoint = config.get("token_endpoint", "")
        self._grant = grant
        self._client_id = config["client_id"]
        self._scope = config.get("scope", "")
        self._client_secret = secrets.get("client_secret_env", "")
        self._refresh_token = secrets.get("refresh_token_env", "")
        #: Names of the variables with the secrets, which the caller may drop from the environment
        self.env_names = tuple(config[key] for key in ("client_secret_env", "refresh_token_env") if key in config)
        self._http = http or UrllibHttp()
        self._clock = clock
        self._lock = threading.Lock()
        self._token = ""
        self._fetched_at = 0.0
        self._expires_at = 0.0
        self._renew_at = 0.0
        self._retry_at = 0.0

    def _call(self, method: Callable[..., tuple[int, Any]], *args: Any) -> tuple[int, Any]:
        """Call the provider, and name the site if there's no response.

        Args:
            method: A method of `Http`.
            *args: Its arguments.

        Returns:
            What it returns.

        Raises:
            TokenError: There was no response.
        """
        try:
            return method(*args)
        except TokenError as error:
            raise TokenError(f"Site {self._site}: {error}") from None

    def _token_endpoint(self) -> str:
        """Find the token endpoint, by OpenID Connect discovery unless it's configured.

        Returns:
            Its URL.

        Raises:
            TokenError: Discovery failed, or names another issuer, or a token
                endpoint that isn't `https`.
        """
        if self._endpoint:
            return self._endpoint
        url = f"{self._issuer.rstrip('/')}/.well-known/openid-configuration"
        status, body = self._call(self._http.get_json, url)
        if status != 200 or not isinstance(body, dict):
            raise TokenError(f"Discovery for site {self._site} failed with status {status}")
        # OpenID Connect Discovery 1.0, section 4.3
        if body.get("issuer") != self._issuer:
            raise TokenError(f"Discovery for site {self._site} names another issuer")
        endpoint = body.get("token_endpoint")
        if not isinstance(endpoint, str):
            raise TokenError(f"Discovery for site {self._site} names no token endpoint")
        try:
            check_url(endpoint, f"The token endpoint of site {self._site}")
        except ValueError as error:
            raise TokenError(str(error)) from None
        self._endpoint = endpoint
        return endpoint

    def _request(self) -> None:
        """Get a new token from the token endpoint, and keep a new refresh token.

        Raises:
            TokenError: The endpoint refused, or answered with no bearer token.
                The message holds the error code of the response at most.
        """
        form = {"grant_type": self._grant}
        if self._grant == "refresh_token":
            form["refresh_token"] = self._refresh_token
        if self._scope:
            form["scope"] = self._scope
        headers = {}
        if self._client_secret:
            # `client_secret_basic` (RFC 6749, section 2.3.1), with both parts form-encoded
            pair = f"{urllib.parse.quote(self._client_id, safe='')}:{urllib.parse.quote(self._client_secret, safe='')}"
            headers["Authorization"] = f"Basic {base64.b64encode(pair.encode()).decode()}"
        else:
            form["client_id"] = self._client_id
        started = self._clock()
        status, body = self._call(self._http.post_form, self._token_endpoint(), form, headers)
        if status != 200 or not isinstance(body, dict):
            code = body.get("error") if isinstance(body, dict) else None
            detail = f" ({code})" if isinstance(code, str) and ERROR_CODE.fullmatch(code) else ""
            raise TokenError(f"The token endpoint of site {self._site} answered with status {status}{detail}")
        if str(body.get("token_type", "")).lower() != "bearer":
            raise TokenError(f"The token endpoint of site {self._site} sent no bearer token")
        token = check_token(str(body.get("access_token", "")), f"The access token of site {self._site}")
        lifetime = body.get("expires_in", DEFAULT_LIFETIME)
        if (
            not isinstance(lifetime, int | float)
            or isinstance(lifetime, bool)
            or not math.isfinite(lifetime)
            or lifetime <= 0
        ):
            lifetime = DEFAULT_LIFETIME
        lifetime = min(lifetime, MAX_LIFETIME)
        # Providers that rotate refresh tokens send a new one, and may revoke the old one
        if self._grant == "refresh_token" and isinstance(body.get("refresh_token"), str) and body["refresh_token"]:
            self._refresh_token = body["refresh_token"]
        self._token = token
        self._fetched_at = started
        self._expires_at = started + lifetime
        self._renew_at = started + lifetime - min(RENEW_BEFORE, lifetime / 2)

    def token(self) -> str:
        """Get a token valid for a while yet, from the cache or the token endpoint.

        After a failed renewal, the provider is asked again only after
        `RETRY_AFTER` seconds; meanwhile, and on failure, the cached token is
        used for as long as it is valid.

        Returns:
            The token.

        Raises:
            TokenError: A new one was due, and couldn't be had, and there's no
                valid one left.
        """
        with self._lock:
            now = self._clock()
            usable = bool(self._token) and now < self._expires_at
            if usable and now < self._renew_at:
                return self._token
            if now < self._retry_at:
                if usable:
                    return self._token
                raise TokenError(f"Site {self._site}: the last renewal failed, next try within {RETRY_AFTER:.0f} s")
            try:
                self._request()
            except TokenError:
                self._retry_at = now + RETRY_AFTER
                if usable:
                    return self._token
                raise
            self._retry_at = 0.0
            return self._token

    def invalidate(self, refused: str) -> None:
        """Forget the cached token if it's the refused one, so that the next call gets a new one.

        Args:
            refused: The token the TES refused. If another request renewed it
                meanwhile, the new one stays, so that a refusal costs one
                renewal, not one per request. A token got less than
                `MIN_RENEW_INTERVAL` seconds ago stays too, so that a TES
                that refuses every token doesn't make each poll a renewal.
        """
        with self._lock:
            if self._token == refused and self._clock() - self._fetched_at >= MIN_RENEW_INTERVAL:
                self._token = ""


def from_site(
    site: str, config: Mapping[str, Any], environ: Mapping[str, str] | None = None, http: Http | None = None
) -> TokenSource | None:
    """Build the token source of a site from its entry in the sites file.

    Args:
        site: Name of the site.
        config: Its entry in the sites file.
        environ: The environment to take secrets from, by default the process's.
        http: How to reach an OAuth provider.

    Returns:
        The source, or `None` if the site has no token.

    Raises:
        ValueError: More than one source, or a source that can't work.
    """
    given = [key for key in ("token", "token_file", "oauth") if key in config]
    if not given:
        return None
    if len(given) > 1:
        raise ValueError(f"Site {site} has more than one token source: {given}")
    if given[0] != "oauth" and not isinstance(config[given[0]], str):
        raise ValueError(f"The {given[0]} of site {site} must be a string")
    if given[0] == "token":
        return StaticToken(site, config["token"])
    if given[0] == "token_file":
        return FileToken(site, config["token_file"])
    return OAuthToken(site, config["oauth"], os.environ if environ is None else environ, http)

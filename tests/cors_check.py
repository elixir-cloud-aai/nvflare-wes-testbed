"""Check the WES's CORS: only for `/ga4gh/wes/v1`, only for the configured origins.

Calls the application over ASGI, in process, so it needs no network and no
HTTP client beyond what the image has. Runs in the image (`cors-check` in
`compose.yaml` and `tests/compose.hub-test.yaml`, which `tests/hub.sh` runs)
or with the WES's dependencies installed:

    python3 tests/cors_check.py
"""

import os
import pathlib
import subprocess
import sys
import tempfile
from collections.abc import Callable
from typing import Any

import anyio

ROOT = pathlib.Path(__file__).resolve().parent.parent
PORTAL = "https://portal.example.org"
LOCAL = "http://localhost:3000"


def call(app: Callable[..., Any], method: str, path: str, headers: dict[str, str]) -> tuple[int, dict[str, str]]:
    """Send one request to an ASGI application.

    Args:
        app: The application.
        method: HTTP method.
        path: Path, as it reaches the application (decoded, as uvicorn passes it).
        headers: Request headers.

    Returns:
        The status, and the response headers, with lower-case names.
    """
    messages: list[dict[str, Any]] = []
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(name.lower().encode(), value.encode()) for name, value in headers.items()],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    anyio.run(app, scope, receive, send)
    start = next(message for message in messages if message["type"] == "http.response.start")
    return start["status"], {name.decode().lower(): value.decode() for name, value in start["headers"]}


def preflight(origin: str, method: str = "POST", headers: str = "authorization") -> dict[str, str]:
    """Headers of a browser's preflight request.

    Args:
        origin: The page's origin.
        method: The method the page wants to use.
        headers: The headers the page wants to send, comma-separated.

    Returns:
        The headers.
    """
    return {"Origin": origin, "Access-Control-Request-Method": method, "Access-Control-Request-Headers": headers}


def raises(function: Callable[[str], object], value: str) -> bool:
    """Whether a function refuses a value with a `ValueError`.

    Args:
        function: The function.
        value: The value.

    Returns:
        Whether it raised.
    """
    try:
        function(value)
    except ValueError:
        return True
    return False


def cors_installed_without_setting() -> bool:
    """Whether the WES installs its CORS middleware with `WES_CORS_ALLOWED_ORIGINS` unset.

    In a process of its own, as the setting is read on import.

    Returns:
        Whether it does.
    """
    environ = {key: value for key, value in os.environ.items() if key != "WES_CORS_ALLOWED_ORIGINS"}
    code = "from wes import app as w; print(any(m.cls is w.WesCorsMiddleware for m in w.app.user_middleware))"
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=environ, capture_output=True, text=True, check=True
    )
    return result.stdout.strip().splitlines()[-1] != "False"


def main() -> None:
    """Check preflights and responses of the WES, with two allowed origins."""
    with tempfile.TemporaryDirectory() as base:
        os.environ["WES_WORKDIR"] = base
        os.environ["WES_OIDC_ISSUER"] = "https://issuer.test/"
        os.environ["WES_CORS_ALLOWED_ORIGINS"] = f" {PORTAL}/ , {LOCAL} "
        os.environ["FL_PROBE_RESPONDER"] = "0"
        sys.path.insert(0, str(ROOT))
        from wes import app as wes

        app = wes.app
        info = "/ga4gh/wes/v1/service-info"
        runs = "/ga4gh/wes/v1/runs"
        status, ok = call(app, "OPTIONS", runs, preflight(PORTAL))
        allowed_headers = {h.strip().lower() for h in ok.get("access-control-allow-headers", "").split(",")}
        allowed_methods = {m.strip() for m in ok.get("access-control-allow-methods", "").split(",")}
        _, local = call(app, "OPTIONS", runs, preflight(LOCAL, "GET"))
        _, get_info = call(app, "GET", info, {"Origin": PORTAL})
        no_token, no_token_headers = call(app, "GET", runs, {"Origin": PORTAL})
        _, other_info = call(app, "GET", info, {"Origin": "https://evil.example.org"})
        other_status, other = call(app, "OPTIONS", runs, preflight("https://evil.example.org"))
        _, prefix = call(app, "OPTIONS", runs, preflight("https://portal.example.org.evil.example.org"))
        _, kits = call(app, "OPTIONS", "/kits/token/site-1.tgz", preflight(PORTAL, "GET"))
        _, csr = call(app, "OPTIONS", "/sites/token/csr", preflight(PORTAL))
        _, kits_get = call(app, "GET", "/kits/token/site-1.tgz", {"Origin": PORTAL})
        _, outputs = call(app, "GET", "/outputs/run/global_model.npy", {"Origin": PORTAL})
        slash_status, _ = call(app, "GET", f"{info}/", {})
        exact_status, exact = call(app, "OPTIONS", "/ga4gh/wes/v1", preflight(PORTAL, "GET"))
        _, lookalike = call(app, "OPTIONS", "/ga4gh/wes/v1x", preflight(PORTAL, "GET"))
        _, docs = call(app, "OPTIONS", "/docs", preflight(PORTAL, "GET"))
        custom_status, _ = call(app, "OPTIONS", runs, preflight(PORTAL, "POST", "authorization,x-custom"))
        put_status, _ = call(app, "OPTIONS", runs, preflight(PORTAL, "PUT"))

        checks = {
            "a preflight from the portal succeeds": status == 200,
            "it allows the portal's origin": ok.get("access-control-allow-origin") == PORTAL,
            "it allows the Authorization header": "authorization" in allowed_headers,
            "it allows the Content-Type header": "content-type" in allowed_headers,
            "it allows GET and POST": {"GET", "POST"} <= allowed_methods,
            "it allows no other method": allowed_methods <= {"GET", "POST", "OPTIONS"},
            "a preflight for PUT fails": put_status == 400,
            "it allows no credentials (cookies), as bearer tokens need none": "access-control-allow-credentials"
            not in ok,
            "it caches the preflight": ok.get("access-control-max-age") == "600",
            "a preflight from the second origin succeeds": local.get("access-control-allow-origin") == LOCAL,
            "service-info carries the portal's origin": get_info.get("access-control-allow-origin") == PORTAL,
            "a 401 still carries the portal's origin, so the page can read it": no_token == 401
            and no_token_headers.get("access-control-allow-origin") == PORTAL,
            "responses vary by origin": "origin" in get_info.get("vary", "").lower(),
            "no origin for another site's GET": "access-control-allow-origin" not in other_info,
            "a preflight from another site fails": other_status == 400 and "access-control-allow-origin" not in other,
            "an origin that only starts like the portal's fails": "access-control-allow-origin" not in prefix,
            "no CORS for /kits": "access-control-allow-origin" not in kits
            and "access-control-allow-origin" not in kits_get,
            "no CORS for /sites": "access-control-allow-origin" not in csr,
            "no CORS for /outputs": "access-control-allow-origin" not in outputs,
            "no CORS for a path that only starts like the WES's": "access-control-allow-origin" not in lookalike,
            "no CORS for /docs": "access-control-allow-origin" not in docs,
            "a header that isn't allowed fails the preflight": custom_status == 400,
            "no redirect for a trailing slash, which would lead to http behind the router": slash_status == 404,
            "CORS for the WES's prefix itself": exact_status == 200
            and exact.get("access-control-allow-origin") == PORTAL,
            "the middleware is installed with the setting": any(
                m.cls is wes.WesCorsMiddleware for m in app.user_middleware
            ),
            "no CORS at all without the setting": not cors_installed_without_setting(),
        }

        # What the setting takes
        parse = wes.parse_cors_origins
        checks["no origins by default"] = parse("") == [] and parse(" , ") == []
        checks["origins without a trailing slash, deduplicated"] = parse(f"{PORTAL}/,{PORTAL}") == [PORTAL]
        for bad in ("*", "portal.example.org", "https://portal.example.org/path", "ftp://portal.example.org", "null"):
            checks[f"refuses {bad!r}"] = raises(parse, bad)
        checks["drops default ports, as browsers send none"] = parse(
            "https://portal.example.org:443,http://localhost:80"
        ) == [PORTAL, "http://localhost"]
        checks["takes a port"] = parse("https://portal.example.org:8443") == ["https://portal.example.org:8443"]
        checks["lower-cases scheme and host, as browsers send them"] = parse("HTTPS://Portal.Example.org") == [PORTAL]

    failed = 0
    for name, passed in checks.items():
        print(f"[{'ok' if passed else 'FAIL'}] {name}")
        failed += not passed
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

"""A thin WES in front of NVFlare, with FL clients as TES tasks. Sandbox only.

Implements the part of the GA4GH WES 1.1 API that the testbed needs, for two
workflow types. `FEDAVG` is federated averaging as a plain workflow, without
NVFlare: rounds of one TES task per site, averaged here (`wes/fedavg.py`,
option C4). For a run of `NVFLARE`, it:

1. creates a root CA for that run alone, through `nvflare cert init`, and
   provisions the server and an admin itself, through `nvflare cert request`,
   `cert approve` and `package` run locally, one after another;
2. starts the FL server, by default as a child process of this service; with
   `FL_SERVER_MODE=tes`, as a TES task of its own (see `compose.server-task.yaml`).
   A child process takes the FL port over from the probe responder, which answers
   node probes on it while no run is active (`wes/probe_responder.py`);
3. submits one TES task per site, each running an FL client that makes its own
   key, sends this service a signing request over `/sites/{token}/csr`, and
   dials out to the server with the certificate that comes back;
4. submits the FLARE job through the FLARE admin API, and waits for it;
5. downloads the global model, shuts the federation down, deletes the CA, and
   hands the FL port back to the probe responder.

Every shortcut in here is listed in `docs/testbed/shortcuts.md`. Authentication
is mandatory, OIDC bearer tokens against one trusted issuer (H5); a caller
only sees and acts on its own runs, and may also be checked against a static
allow-list (H22). One run at a time, state in memory.
"""

import contextlib
import errno
import hashlib
import json
import logging
import os
import pathlib
import re
import secrets
import shutil
import socket
import subprocess
import tarfile
import threading
import time
import urllib.parse
import uuid
from collections.abc import AsyncIterator, Iterable, Mapping, MutableMapping
from typing import Annotated, Any, NamedTuple

import anyio
import jwt
import requests
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from wes import fedavg, tokens
from wes.probe_responder import ProbeResponder, responder_enabled

logger = logging.getLogger("wes")

BASE = pathlib.Path(os.environ.get("WES_WORKDIR", "/tmp/wes"))
PUBLIC_URL = os.environ.get("WES_INTERNAL_URL", "http://fl-hub:8080")
FL_HOST = os.environ.get("FL_SERVER_NAME", "fl-hub")
IMAGE = os.environ.get("FL_IMAGE", "nvflare-testbed:local")
JOBS = pathlib.Path(os.environ.get("FL_JOBS", "/app/testset/job"))
# {"site-1": {"tes": "http://funnel-site-1:8000", "data": "file:///data/site-1.csv"}, ...},
# from a file if `WES_SITES_FILE` is set, as a site's optional `token` for its TES is a secret.
# In place of `token`, a site may name a `token_file` or an `oauth` provider (`wes/tokens.py`)
SITES_FILE = os.environ.get("WES_SITES_FILE", "")


def load_sites(
    text: str, environ: Mapping[str, str] | None = None
) -> tuple[dict[str, dict[str, Any]], dict[str, tokens.TokenSource]]:
    """Read the sites, and check their token sources, as a bad one would end up in errors and logs.

    Args:
        text: The sites, as JSON.
        environ: The environment that `oauth` sources take their secrets from,
            by default the process's.

    Returns:
        The sites, and the token source of each site that has one (`token`,
        `token_file` or `oauth`, see `wes/tokens.py`).

    Raises:
        ValueError: A site is named `server`, which stands for the task of the FL
            server, or a token source can't work, or would send tokens over
            plain HTTP. The message doesn't hold a token or secret.
    """
    sites: dict[str, dict[str, Any]] = json.loads(text)
    if "server" in sites:
        raise ValueError("A site can't be named server")
    environ = os.environ if environ is None else environ
    sources: dict[str, tokens.TokenSource] = {}
    # Refresh token -> site, to find one in two sites, by the same variable or another
    refresh_tokens: dict[str, str] = {}
    # Backend -> site: a backend pins the tasks of one site only
    backends: dict[str, str] = {}
    for name, site in sites.items():
        if "backend" in site:
            backend = site["backend"]
            if not (isinstance(backend, str) and backend):
                raise ValueError(f"The backend of site {name} must be a non-empty string")
            if backend in backends:
                raise ValueError(f"Sites {backends[backend]} and {name} have the same backend")
            backends[backend] = name
        source = tokens.from_site(name, site, environ)
        if source is None:
            continue
        if not str(site.get("tes", "")).startswith("https://"):
            raise ValueError(f"The token of site {name} only goes to a TES over https")
        claim_refresh_token(refresh_tokens, f"site {name}", site, environ)
        sources[name] = source
    return sites, sources


def claim_refresh_token(
    owners: dict[str, str], owner: str, config: Mapping[str, Any], environ: Mapping[str, str]
) -> None:
    """Note the refresh token of a token source, unless another source has it already.

    Each source renews on its own: with a provider that rotates refresh tokens, a shared
    one would be spent by one source and refused (or the whole family revoked) for the
    other.

    Args:
        owners: The owner of each refresh token so far, updated here.
        owner: Who the source is for, as in messages (e.g. `site site-1`).
        config: The token source, with `oauth` if it is one.
        environ: The environment with the refresh token.

    Raises:
        ValueError: Another source has the same refresh token, by the same variable or
            another. The message doesn't hold the token.
    """
    variable = config.get("oauth", {}).get("refresh_token_env")
    if not variable:
        return
    value = environ[variable]
    if value in owners:
        raise ValueError(f"The {owners[value]} and the {owner} share a refresh token")
    owners[value] = owner


def load_gateway(
    url: str,
    token_url: str,
    source_json: str,
    sites: Mapping[str, Mapping[str, Any]],
    environ: Mapping[str, str] | None = None,
) -> tokens.TokenSource | None:
    """Read the token source of the gateway, and check it as the sources of sites.

    Args:
        url: The URL of the gateway (`TES_GATEWAY_URL`), empty without one.
        token_url: The token URL of the fake identity provider of the local tests
            (`TES_GATEWAY_TOKEN_URL`), empty without one.
        source_json: The token source of the gateway (`TES_GATEWAY_TOKEN_SOURCE`), a JSON
            object with one of the keys of a site's token source (`token`, `token_file`
            or `oauth`), empty without one.
        sites: The sites, whose `oauth` sources must not share a refresh token with it.
        environ: The environment that an `oauth` source takes its secrets from, by
            default the process's.

    Returns:
        The source, or `None` without a gateway, or with the token URL.

    Raises:
        ValueError: A source without a gateway, or over plain HTTP, or with the token URL,
            or one that can't work, or a gateway without a source or the token URL. The message doesn't hold a token or secret.
    """
    if not source_json:
        if url and not token_url:
            raise ValueError("A gateway (TES_GATEWAY_URL) needs a token source (TES_GATEWAY_TOKEN_SOURCE)")
        return None
    if not url:
        raise ValueError("A gateway token source needs a gateway (TES_GATEWAY_URL)")
    if token_url:
        raise ValueError("Set either TES_GATEWAY_TOKEN_SOURCE or TES_GATEWAY_TOKEN_URL")
    if not url.startswith("https://"):
        raise ValueError("The token of the gateway only goes to a gateway over https")
    try:
        config = json.loads(source_json)
    except json.JSONDecodeError:
        # Without the error, which may quote the token
        raise ValueError("The gateway token source isn't JSON") from None
    if not isinstance(config, dict):
        raise ValueError("The gateway token source must be a JSON object")  # noqa: TRY004 - a config error, as the others
    environ = os.environ if environ is None else environ
    source = tokens.from_site("gateway", config, environ)
    if source is None:
        raise ValueError("The gateway token source needs token, token_file or oauth")
    owners: dict[str, str] = {}
    for name, site in sites.items():
        # The sites' variables may be gone already (`drop_secrets`), once their sources hold them
        if (variable := site.get("oauth", {}).get("refresh_token_env")) and variable in environ:
            claim_refresh_token(owners, f"site {name}", site, environ)
    claim_refresh_token(owners, "gateway", config, environ)
    return source


def drop_secrets(environ: MutableMapping[str, str], sources: Iterable[tokens.TokenSource]) -> None:
    """Remove the token sources' secrets from the environment, once they hold them.

    Args:
        environ: The environment, changed here: without `TES_GATEWAY_TOKEN_SOURCE` and
            the variables that the sources read (`env_names`).
        sources: The token sources of the sites and the gateway.
    """
    for name in {"TES_GATEWAY_TOKEN_SOURCE", *(name for source in sources for name in source.env_names)}:
        environ.pop(name, None)


SITES, TOKENS = load_sites(pathlib.Path(SITES_FILE).read_text() if SITES_FILE else os.environ.get("WES_SITES", "{}"))
# If set, tasks go to this gateway (proTES), pinned to the TES of the site (or its `backend`) by tag
# Without a trailing slash or the API's path, which `tes_base` appends
TES_GATEWAY = os.environ.get("TES_GATEWAY_URL", "").rstrip("/").removesuffix("/ga4gh/tes/v1").rstrip("/")
# The fake identity provider of the local tests; real gateways take TES_GATEWAY_TOKEN_SOURCE
TES_GATEWAY_TOKEN_URL = os.environ.get("TES_GATEWAY_TOKEN_URL", "")
# One token for all tasks through the gateway, whoever starts the run (H25)
GATEWAY_TOKEN = load_gateway(TES_GATEWAY, TES_GATEWAY_TOKEN_URL, os.environ.get("TES_GATEWAY_TOKEN_SOURCE", ""), SITES)
FL_SERVER_MODE = os.environ.get("FL_SERVER_MODE", "local")
FL_SERVER_TES = os.environ.get("FL_SERVER_TES", "")
# `grpc` or `http`, the latter (WebSocket) for sites that only allow port 443 out
FL_SCHEME = os.environ.get("FL_SCHEME", "grpc")
FL_PORT = int(os.environ.get("FL_PORT", "8002"))
# The sources hold the secrets now, and all settings are read: child processes (`nvflare`, the
# FL server) aren't passed them
drop_secrets(os.environ, [*TOKENS.values(), *([GATEWAY_TOKEN] if GATEWAY_TOKEN is not None else [])])
ORG = "testbed"
ADMIN_PORT = 8003
START_TIMEOUT = 180
JOB_TIMEOUT = 600
# Seconds for all tasks of a round of a `FEDAVG` run to end
ROUND_TIMEOUT = fedavg.parse_timeout(os.environ.get("FEDAVG_ROUND_TIMEOUT", "300"))
MAX_CSR_SIZE = 1 << 20  # a CSR package is a few KB; this just bounds memory
# What gRPC logs, in the FL server's output, when it can't bind the FL port; the server starts anyway
BIND_FAILURE = "Failed to add port"
# What NVFlare logs for a port it did bind
BOUND_PORT = r"added (?:secure|insecure) port at \S*:{port}\b"


def make_responder(setting: str | None, mode: str, port: int) -> ProbeResponder | None:
    """Make the probe responder for the FL port, if this service runs one.

    Args:
        setting: The value of `FL_PROBE_RESPONDER`, or `None` if it isn't set (on, as when empty).
        mode: `FL_SERVER_MODE`.
        port: The FL port.

    Returns:
        The responder, not started yet, or `None` if it's switched off, or the FL
        server runs in a TES task: then the FL port of this container isn't the
        one that sites dial.

    Raises:
        ValueError: The setting is neither on nor off.
    """
    if not responder_enabled(setting) or mode == "tes":
        return None
    return ProbeResponder(port)


# Answers node probes on the FL port between runs (`wes/probe_responder.py`)
RESPONDER = make_responder(os.environ.get("FL_PROBE_RESPONDER"), FL_SERVER_MODE, FL_PORT)
TERMINAL_TES = {"COMPLETE", "EXECUTOR_ERROR", "SYSTEM_ERROR", "CANCELED", "PREEMPTED"}
# Mandatory (H5): empty means no issuer is trusted, so no caller can check out
OIDC_ISSUER = os.environ.get("WES_OIDC_ISSUER", "")
OIDC_AUDIENCE = os.environ.get("WES_OIDC_AUDIENCE", "fl-wes")
OIDC_ALGORITHMS = [a.strip() for a in os.environ.get("WES_OIDC_ALGORITHMS", "RS256").split(",") if a.strip()]
# Discovery and the JWKS it names must be https, except for an explicit local
# escape hatch: the sandbox's own fake identity provider (H10) has no TLS
OIDC_ALLOW_HTTP = bool(os.environ.get("WES_OIDC_ALLOW_HTTP", ""))
# Empty allows any authenticated subject (H22): a shortcut, not group/role RBAC
ALLOWED_SUBS = {s.strip() for s in os.environ.get("WES_OIDC_ALLOWED_SUBS", "").split(",") if s.strip()}
if not OIDC_ISSUER:
    logger.warning("No WES_OIDC_ISSUER is configured: every run and most endpoints will be refused")


def start_responder() -> None:
    """Start the probe responder, if there is one, without ever failing the caller.

    Probes are a convenience: a hub that can't start the thread still serves runs.
    """
    if RESPONDER is None:
        return
    try:
        RESPONDER.start()
    except Exception:  # e.g. no thread left in the pod's limits: runs must go on
        logger.exception("Couldn't start the probe responder on port %d", RESPONDER.port)


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Answer node probes on the FL port while this service runs, until a run takes it.

    Args:
        _app: The application.

    Yields:
        Nothing, while the service runs.
    """
    start_responder()
    try:
        yield
    finally:
        if RESPONDER is not None:
            await anyio.to_thread.run_sync(RESPONDER.stop)


app = FastAPI(title="Thin WES for NVFlare (sandbox)", lifespan=lifespan)

# The WES API, the only part of the service that browsers may call from other
# origins. Keep it in sync with the paths of the WES endpoints below, and with
# the Route of the chart (`route-wes.yaml`)
WES_PREFIX = "/ga4gh/wes/v1"
# An origin as browsers send it: scheme, host and an optional port, nothing else
ORIGIN = re.compile(r"https?://[a-z0-9]([a-z0-9.-]*[a-z0-9])?(:[0-9]{1,5})?")


def parse_cors_origins(value: str) -> list[str]:
    """Read the origins whose pages may call the WES API, from `WES_CORS_ALLOWED_ORIGINS`.

    Args:
        value: Origins, comma-separated, such as `https://portal.example.org`; a
            trailing slash is dropped, and scheme and host are lower-cased, as
            browsers send them.

    Returns:
        The origins, each once, in order; empty for none.

    Raises:
        ValueError: An entry isn't an `http` or `https` origin without a path,
            such as `*`: the WES allows named origins only.
    """
    origins: list[str] = []
    for entry in (part.strip() for part in value.split(",")):
        if not entry:
            continue
        origin = entry.removesuffix("/").lower()
        if not ORIGIN.fullmatch(origin):
            raise ValueError(
                f"WES_CORS_ALLOWED_ORIGINS: {entry!r} isn't an origin such as https://portal.example.org"
                " (scheme and host, an optional port, no path, no wildcard)"
            )
        if origin not in origins:
            origins.append(origin)
    return origins


class WesCorsMiddleware:
    """CORS for the WES API alone: `/kits`, `/sites` and `/outputs` stay out of reach of other origins' pages."""

    def __init__(self, asgi_app: Any, origins: list[str]) -> None:
        """Wrap an application.

        Args:
            asgi_app: The application.
            origins: The origins allowed to call the WES API.
        """
        self.app = asgi_app
        # Bearer tokens in a header, never cookies, so no credentials
        self.cors = CORSMiddleware(
            asgi_app,
            allow_origins=origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
            max_age=600,
        )

    async def __call__(self, scope: MutableMapping[str, Any], receive: Any, send: Any) -> None:
        """Handle a request, with CORS if it is for the WES API.

        Args:
            scope: The ASGI scope.
            receive: The ASGI receive channel.
            send: The ASGI send channel.
        """
        # Only HTTP requests: lifespan events pass through as they are
        path = scope.get("path", "") if scope["type"] == "http" else ""
        if path == WES_PREFIX or path.startswith(f"{WES_PREFIX}/"):
            await self.cors(scope, receive, send)
        else:
            await self.app(scope, receive, send)


CORS_ALLOWED_ORIGINS = parse_cors_origins(os.environ.get("WES_CORS_ALLOWED_ORIGINS", ""))
if CORS_ALLOWED_ORIGINS:
    app.add_middleware(WesCorsMiddleware, origins=CORS_ALLOWED_ORIGINS)
    logger.info("CORS: pages of %s may call %s", ", ".join(CORS_ALLOWED_ORIGINS), WES_PREFIX)

RUNS: dict[str, dict[str, Any]] = {}
KITS: dict[str, pathlib.Path] = {}
# Token -> (run_id, site) of a site's one slot to send its certificate signing
# request. Unlike KITS, what it gives out never includes a private key (H4).
CSR_TOKENS: dict[str, tuple[str, str]] = {}
LOCK = threading.Lock()


PROFILE = """\
name: {name}
scheme: {scheme}
connection_security: mtls
server:
  host: {host}
  fed_learn_port: {fl_port}
  admin_port: {admin_port}
"""


def parse_fields(output: str) -> dict[str, str]:
    """Parse the `key: value` lines an `nvflare cert`/`nvflare package` command prints.

    Args:
        output: Its stdout.

    Returns:
        The fields, by the first colon of each line.
    """
    fields: dict[str, str] = {}
    for line in output.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip()] = value.strip()
    return fields


def server_participant_yaml(project: str, name: str, org: str) -> str:
    """Build the FL server's one-participant descriptor for `nvflare cert request`.

    Args:
        project: Name of the project, as in its `project_profile.yaml`.
        name: Name of the server.
        org: Its organization.

    Returns:
        The YAML, with the server's own name as a `host_names` entry, as
        that's the name clients dial out to and must find in its certificate.
    """
    return f"name: {project}\n\nparticipants:\n  - name: {name}\n    type: server\n    org: {org}\n    host_names: [{name}]\n"


def admin_participant_yaml(project: str, name: str, org: str) -> str:
    """Build the admin's one-participant descriptor for `nvflare cert request`.

    Args:
        project: Name of the project, as in its `project_profile.yaml`.
        name: Name of the admin.
        org: Its organization.

    Returns:
        The YAML, with a fixed `role: lead` (NVFlare also allows `org_admin`
        and `member`; this run only ever has the one admin).
    """
    return f"name: {project}\n\nparticipants:\n  - name: {name}\n    type: admin\n    org: {org}\n    role: lead\n"


def init_ca(run_dir: pathlib.Path, project: str) -> str:
    """Create the root CA of a run's federation.

    Args:
        run_dir: Working directory of the run. Gets `project_profile.yaml` and `ca`.
        project: Name of the project.

    Returns:
        The CA's SHA-256 fingerprint, so sites can check it out of band.
    """
    (run_dir / "project_profile.yaml").write_text(
        PROFILE.format(name=project, scheme=FL_SCHEME, host=FL_HOST, fl_port=FL_PORT, admin_port=ADMIN_PORT)
    )
    result = subprocess.run(
        ["nvflare", "cert", "init", "--profile", "project_profile.yaml", "-o", "ca", "--valid-days", "2"],
        cwd=run_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    return parse_fields(result.stdout)["rootca_fingerprint_sha256"]


def provision_locally(run_dir: pathlib.Path, project: str, name: str, kind: str) -> pathlib.Path:
    """Provision a participant this service holds itself: the FL server or the admin.

    Unlike a site (`sign_csr`), there's no secret to keep off this service for
    these two, so it runs all of `nvflare cert request`, `approve` and
    `package` itself, instead of a site's one network round trip.

    Args:
        run_dir: Working directory of the run, with `project_profile.yaml` and `ca`.
        project: Name of the project.
        name: Name of the participant.
        kind: `server` or `admin`.

    Returns:
        The directory of its startup kit.
    """
    work = run_dir / name
    work.mkdir()
    participant = (
        server_participant_yaml(project, name, ORG) if kind == "server" else admin_participant_yaml(project, name, ORG)
    )
    (work / "participant.yaml").write_text(participant)
    subprocess.run(
        ["nvflare", "cert", "request", "--participant", "participant.yaml"],
        cwd=work,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            "nvflare",
            "cert",
            "approve",
            f"{name}/{name}.request.zip",
            "--ca-dir",
            "../ca",
            "--profile",
            "../project_profile.yaml",
            "--out",
            f"{name}/{name}.signed.zip",
        ],
        cwd=work,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["nvflare", "package", f"{name}/{name}.signed.zip"],
        cwd=work,
        check=True,
        capture_output=True,
        text=True,
    )
    return work / "workspace" / project / "prod_00" / name


def start_server(kit_dir: pathlib.Path, log_path: pathlib.Path) -> subprocess.Popen[bytes]:
    """Start the FL server as a child process.

    Args:
        kit_dir: Directory of its startup kit.
        log_path: File for the output of the server.

    Returns:
        The process.
    """
    with log_path.open("wb") as log:
        return subprocess.Popen(
            [
                "python3",
                "-u",
                "-m",
                "nvflare.private.fed.app.server.server_train",
                "-m",
                str(kit_dir),
                "-s",
                "fed_server.json",
                "--set",
                "secure_train=true",
                f"org={ORG}",
                "config_folder=config",
            ],
            cwd=kit_dir,
            stdout=log,
            stderr=subprocess.STDOUT,
        )


def wait_for_port(host: str, port: int, timeout: float) -> None:
    """Wait until a port accepts connections.

    Args:
        host: The host.
        port: The port.
        timeout: Seconds to wait.

    Raises:
        TimeoutError: The port stayed closed.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return
        except OSError:
            time.sleep(1)
    raise TimeoutError(f"Nothing listens on {host}:{port}")


def ensure_port_free(port: int) -> None:
    """Check that nothing in this container listens on a port yet.

    The FL server only logs that it can't bind its port, and starts anyway, so
    sites would dial out to whatever holds it, never join, and the run would
    end with a timeout that names no cause.

    Args:
        port: The port.

    Raises:
        RuntimeError: Something listens on it, or it can't be bound for another reason.
    """
    try:
        with socket.create_server(("", port)):
            pass
    except OSError as error:
        if error.errno == errno.EADDRINUSE:
            raise RuntimeError(
                f"The FL port {port} is in use in the hub's container, such as by a probe listener"
            ) from error
        raise RuntimeError(f"The FL port {port} can't be bound: {error.strerror}") from error


def check_server_bound(log_path: pathlib.Path, port: int, timeout: float = 10) -> None:
    """Check that the FL server got its port, by its log.

    `ensure_port_free` can't see a listener that starts after it, or one on
    another address family, and the FL server starts anyway without its port.
    It binds the FL and admin ports at the same time, so this waits for the
    FL port's own line: NVFlare's for a bound port (`BOUND_PORT`), or gRPC's
    for a failure (`BIND_FAILURE`). With neither in time, as with other
    wording, the run goes on.

    Args:
        log_path: File with the output of the server.
        port: The FL port.
        timeout: Seconds to wait for either line.

    Raises:
        RuntimeError: The server logged that it couldn't bind the port.
    """
    bound = re.compile(BOUND_PORT.format(port=port))
    deadline = time.monotonic() + timeout
    while True:
        log = log_path.read_text(errors="replace")
        if BIND_FAILURE in log:
            raise RuntimeError(f"The FL port {port} is in use in the hub's container: the FL server couldn't bind it")
        if bound.search(log) or time.monotonic() >= deadline:
            return
        time.sleep(0.2)


def publish_kit(kit_dir: pathlib.Path, run_dir: pathlib.Path) -> tuple[str, str]:
    """Pack a startup kit, and serve it under an unguessable path.

    Only the FL server's kit still travels this way (`FL_SERVER_MODE=tes`): a
    site's kit never exists as a whole in one place (`sign_csr`).

    Args:
        kit_dir: Directory of the startup kit.
        run_dir: Working directory of the run.

    Returns:
        The token of the kit and its URL.
    """
    name = kit_dir.name
    token = secrets.token_urlsafe(32)
    archive = run_dir / f"{name}.tgz"
    with tarfile.open(archive, "w:gz") as tar:
        for entry in kit_dir.iterdir():
            tar.add(entry, arcname=entry.name)
    KITS[token] = archive
    return token, f"{PUBLIC_URL}/kits/{token}/{name}.tgz"


def site_source(site: str) -> tokens.TokenSource | None:
    """Get the token source for the requests of a site.

    Args:
        site: Name of the site, or `server` for the task of the FL server.

    Returns:
        With a gateway, its source (`TES_GATEWAY_TOKEN_SOURCE`) for all sites, if
        it has one, and none for the FL server, whose TES isn't the gateway: the
        token of a site is for its TES alone, and never goes to a gateway (H25).
        Without one, the site's source, if any. `None` with the token URL of the
        local tests, which `tes_headers` asks itself.
    """
    if TES_GATEWAY_TOKEN_URL:
        return None
    if TES_GATEWAY:
        # The task of the FL server goes straight to its TES (`FL_SERVER_TES`), never to the gateway
        return GATEWAY_TOKEN if site in SITES else None
    return TOKENS.get(site)


def tes_headers(site: str) -> dict[str, str]:
    """Get the headers for the TES of a site, or the gateway if there is one.

    Args:
        site: Name of the site, or `server` for the task of the FL server.

    Returns:
        The headers: an access token if there's one, else none. A site's
        token is read or renewed here, when it's needed (`wes/tokens.py`).

    Raises:
        tokens.TokenError: The site's token couldn't be had.
    """
    if TES_GATEWAY_TOKEN_URL:
        # A token of the fake identity provider is for the gateway, which the FL server's task skips
        token = requests.get(TES_GATEWAY_TOKEN_URL, timeout=10).json()["access_token"] if site in SITES else ""
    else:
        source = site_source(site)
        token = source.token() if source is not None else ""
    return {"Authorization": f"Bearer {token}"} if token else {}


def tes_request(method: str, site: str, url: str, **kwargs: Any) -> requests.Response:
    """Send a request to the TES of a site, or the gateway, with the site's token.

    If the TES refuses the token (`401`) and the site's token can be renewed,
    it is renewed, and the request is sent once more.

    Args:
        method: The HTTP method.
        site: Name of the site, or `server` for the task of the FL server.
        url: The URL.
        **kwargs: For `requests.request`, but no `headers`.

    Returns:
        The response.

    Raises:
        tokens.TokenError: The site's token couldn't be had.
    """
    headers = tes_headers(site)
    reply = requests.request(method, url, headers=headers, **kwargs)
    source = site_source(site)
    if reply.status_code == 401 and source is not None and source.renewable:
        logger.info("TES of %s refused the token, renewing it", site)
        source.invalidate(headers.get("Authorization", "").removeprefix("Bearer "))
        try:
            renewed = tes_headers(site)
        except tokens.TokenError as error:
            # The refusal stands, as for a token that can't be renewed
            # TokenError messages hold no token or secret (wes/tokens.py, tests/tokens_test.py)
            logger.warning("Couldn't renew the token of %s: %s", site, error)  # nosemgrep
            return reply
        if renewed != headers:
            reply = requests.request(method, url, headers=renewed, **kwargs)
    return reply


def tes_base(site: str) -> str:
    """Get the base URL to submit the tasks of a site to.

    Args:
        site: Name of the site.

    Returns:
        The URL of the gateway if there is one, else of the TES of the site.
    """
    return f"{TES_GATEWAY or SITES[site]['tes']}/ga4gh/tes/v1"


def issue_csr_token(run_id: str, site: str) -> tuple[str, str]:
    """Mint a site's one slot to send its certificate signing request.

    Args:
        run_id: Identifier of the run.
        site: Name of the site.

    Returns:
        The token, and the URL to send the request to.
    """
    token = secrets.token_urlsafe(32)
    CSR_TOKENS[token] = (run_id, site)
    return token, f"{PUBLIC_URL}/sites/{token}/csr"


def client_task(run_id: str, site: str, project: str, csr_url: str, fingerprint: str) -> dict[str, Any]:
    """Build the TES task of an FL client.

    Args:
        run_id: Identifier of the run.
        site: Name of the site.
        project: Name of the project, so the client's own request names the same one.
        csr_url: Where the client sends its certificate signing request.
        fingerprint: SHA-256 fingerprint of the run's root CA, for the client to check out of band.

    Returns:
        The task. The data of the site is named by a URL that only resolves at
        the site: it never passes through this service. The site makes its own
        key here, and never sends it anywhere (H4): only a signing request
        travels, over `csr_url`, and only once this task is already running.
    """
    task: dict[str, Any] = {
        "name": f"fl-client-{site}-{run_id[:8]}",
        "description": "NVFlare client of a WES run (sandbox)",
        "inputs": [
            {"name": "data", "url": SITES[site]["data"], "path": f"/data/{site}.csv", "type": "FILE"},
        ],
        "executors": [
            {
                "image": IMAGE,
                "command": ["fl-client", site, ORG, project, csr_url, fingerprint],
                "env": {"FL_DATA": f"/data/{site}.csv", "HOME": "/tmp"},
            }
        ],
        "resources": {"cpu_cores": 1, "ram_gb": 1.0, "disk_gb": 1.0},
        "tags": {"wes_run_id": run_id, "site": site},
    }
    return pin_to_site(task, site)


def pin_to_site(task: dict[str, Any], site: str) -> dict[str, Any]:
    """Pin a task to the TES of its site, if it goes through a gateway.

    Args:
        task: The task, changed in place.
        site: Name of the site.

    Returns:
        The task, with the tag `gateway.backends` if there's a gateway: the site's
        `backend` (an identifier of the gateway's TES instance, or a URL), else
        the URL of its TES. Without one, the task goes straight to the TES of the
        site anyway.
    """
    if TES_GATEWAY:
        backend = SITES[site].get("backend") or SITES[site]["tes"]
        task["tags"]["gateway.backends"] = json.dumps({"type": "allow", "backends": [backend]})
    return task


def server_task(run_id: str, kit_url: str) -> dict[str, Any]:
    """Build the TES task of the FL server, for `FL_SERVER_MODE=tes`.

    Args:
        run_id: Identifier of the run.
        kit_url: URL of the server's startup kit.

    Returns:
        The task. That clients can reach it is not something a TES task can ask
        for: it works here because `compose.server-task.yaml` configures that
        TES to give its tasks a fixed name on the networks of the sites.
    """
    return {
        "name": f"fl-server-{run_id[:8]}",
        "inputs": [{"name": "kit", "url": kit_url, "path": "/kit/kit.tgz", "type": "FILE"}],
        "executors": [
            {
                "image": IMAGE,
                "command": ["fl-server", ORG, "/kit/kit.tgz"],
                "env": {"HOME": "/tmp"},
            }
        ],
        "resources": {"cpu_cores": 1, "ram_gb": 1.0, "disk_gb": 1.0},
        "tags": {"wes_run_id": run_id, "site": "server"},
    }


def wait_for_clients(session: Any, run: dict[str, Any], sites: list[str], timeout: float) -> None:
    """Wait until all sites have joined the federation.

    Args:
        session: FLARE API session.
        run: The run, whose TES tasks must stay alive meanwhile.
        sites: Names of the sites.
        timeout: Seconds to wait.

    Raises:
        RuntimeError: A TES task ended before its site joined.
        TimeoutError: Not all sites joined in time.
    """
    deadline = time.monotonic() + timeout
    joined: set[str] = set()
    while time.monotonic() < deadline:
        joined = {client.name for client in session.get_system_info().client_info}
        if joined >= set(sites):
            return
        update_tasks(run)
        ended = [task for task in run["tasks"] if task["state"] in TERMINAL_TES]
        if ended:
            raise RuntimeError(f"Tasks ended early: {[(task['site'], task['state']) for task in ended]}")
        time.sleep(2)
    raise TimeoutError(f"Sites joined: {sorted(joined)} of {sites}")


def update_tasks(run: dict[str, Any], wait: float = 0) -> None:
    """Refresh the states of the TES tasks of a run.

    Args:
        run: The run.
        wait: Seconds to wait for all tasks to finish.
    """
    deadline = time.monotonic() + wait
    while True:
        for task in run["tasks"]:
            # A TES out of reach must neither end a run's cleanup, nor look like a task's end
            try:
                reply = tes_request(
                    "GET", task["site"], f"{task['base']}/tasks/{task['id']}", params={"view": "MINIMAL"}, timeout=30
                )
                if reply.ok:
                    task["state"] = reply.json().get("state", "UNKNOWN")
            except requests.RequestException:
                logger.warning("TES of %s is out of reach", task["site"])
                continue
            except tokens.TokenError as error:
                # TokenError messages hold no token or secret (wes/tokens.py, tests/tokens_test.py)
                logger.warning("No token for the TES of %s: %s", task["site"], error)  # nosemgrep
                continue
            except Exception as error:  # noqa: BLE001 - e.g. a malformed reply: the cleanup of a run must go on
                logger.warning("Couldn't update the task of %s: %s", task["site"], type(error).__name__)
        if all(task["state"] in TERMINAL_TES for task in run["tasks"]) or time.monotonic() >= deadline:
            return
        time.sleep(2)


def tasks_alive(session: Any, job_id: str, meta: dict[str, Any], run: dict[str, Any]) -> bool:
    """Tell whether to keep waiting for a job, as a callback of the FLARE API.

    A client that dies leaves the job waiting for its result until the job times
    out, so the states of the TES tasks are the quicker signal.

    Args:
        session: FLARE API session.
        job_id: Identifier of the job.
        meta: Metadata of the job.
        run: The run.

    Returns:
        Whether all TES tasks are still running.
    """
    update_tasks(run)
    return not any(task["state"] in TERMINAL_TES for task in run["tasks"])


def cancel_tasks(run: dict[str, Any]) -> None:
    """Cancel the TES tasks of a run that are still running.

    Args:
        run: The run.
    """
    for task in run["tasks"]:
        if task["state"] not in TERMINAL_TES:
            try:
                tes_request("POST", task["site"], f"{task['base']}/tasks/{task['id']}:cancel", timeout=30)
            except Exception:  # noqa: BLE001 - the cleanup of a run must go on
                logger.warning("Couldn't cancel the task of %s", task["site"])


def execute(run_id: str, job_dir: pathlib.Path, sites: list[str], submitter: str) -> None:
    """Carry out a run, in the background.

    Args:
        run_id: Identifier of the run.
        job_dir: Directory of the FLARE job.
        sites: Names of the sites.
        submitter: The caller's validated identity, as the FLARE admin's name.
    """
    from nvflare.fuel.flare_api.flare_api import new_secure_session

    run = RUNS[run_id]
    run_dir = BASE / run_id
    server: subprocess.Popen[bytes] | None = None
    slots: list[str] = []
    final_state = "SYSTEM_ERROR"
    try:
        run["state"] = "INITIALIZING"
        run_dir.mkdir(parents=True)
        if FL_SERVER_MODE != "tes":
            # The probe responder hands the port over first; a listener of anyone else still fails the run.
            # A responder that is slow to end fails the run only if it still holds the port
            released = RESPONDER is None or RESPONDER.stop()
            try:
                ensure_port_free(FL_PORT)
            except RuntimeError as error:
                if not released:
                    raise RuntimeError(f"The probe responder didn't release the FL port {FL_PORT}") from error
                raise
        project = f"run{run_id[:8]}"
        fingerprint = init_ca(run_dir, project)
        server_kit = provision_locally(run_dir, project, FL_HOST, "server")
        admin_kit = provision_locally(run_dir, project, submitter, "admin")
        if FL_SERVER_MODE == "tes":
            token, kit_url = publish_kit(server_kit, run_dir)
            slots.append(token)
            base = f"{FL_SERVER_TES}/ga4gh/tes/v1"
            reply = requests.post(f"{base}/tasks", json=server_task(run_id, kit_url), timeout=60)
            reply.raise_for_status()
            run["tasks"].append({"site": "server", "id": reply.json()["id"], "base": base, "state": "QUEUED"})
            wait_for_port(FL_HOST, ADMIN_PORT, START_TIMEOUT)
        else:
            server = start_server(server_kit, run_dir / "server.log")
            wait_for_port("127.0.0.1", ADMIN_PORT, START_TIMEOUT)
            check_server_bound(run_dir / "server.log", FL_PORT)
        for site in sites:
            token, csr_url = issue_csr_token(run_id, site)
            slots.append(token)
            base = tes_base(site)
            reply = tes_request(
                "POST", site, f"{base}/tasks", json=client_task(run_id, site, project, csr_url, fingerprint), timeout=60
            )
            reply.raise_for_status()
            run["tasks"].append({"site": site, "id": reply.json()["id"], "base": base, "state": "QUEUED"})
        session = new_secure_session(submitter, str(admin_kit), timeout=60)
        try:
            run["state"] = "RUNNING"
            wait_for_clients(session, run, sites, START_TIMEOUT)
            # FLARE signs a job in place, and the image may be read-only to this user
            job_copy = shutil.copytree(job_dir, run_dir / "job" / job_dir.name)
            job_id = session.submit_job(str(job_copy))
            run["flare_job_id"] = job_id
            code, meta = session.monitor_job_and_return_job_meta(job_id, JOB_TIMEOUT, 2, tasks_alive, run)
            status = (meta or {}).get("status", "UNKNOWN")
            run["flare_job_status"] = status
            if not status.startswith("FINISHED"):
                session.abort_job(job_id)
                raise RuntimeError(f"Job ended with {code}, status {status}; tasks: {run['tasks']}")
            result = session.download_job_result(job_id, str(run_dir / "result"))
            models = list(pathlib.Path(result).rglob("server.npy"))
            if models:
                shutil.copy(models[0], run_dir / "global_model.npy")
                run["outputs"]["global_model"] = f"/outputs/{run_id}/global_model.npy"
            session.shutdown("all", wait=False)
        finally:
            session.close()
        update_tasks(run, wait=120)
        tasks_ok = all(task["state"] == "COMPLETE" for task in run["tasks"])
        job_ok = run.get("flare_job_status") == "FINISHED:COMPLETED" and "global_model" in run["outputs"]
        final_state = "COMPLETE" if tasks_ok and job_ok else "EXECUTOR_ERROR"
    except Exception as error:  # the run fails, the service stays
        logger.exception("Run %s failed", run_id)
        run["error"] = repr(error)
    finally:
        update_tasks(run)
        cancel_tasks(run)
        update_tasks(run, wait=30)
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=30)
            except subprocess.TimeoutExpired:
                server.kill()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    logger.warning("The FL server of run %s didn't end after a kill", run_id)
        # Before the run ends, so that no next run can start in between. It retries while the port
        # is still held, such as by a server that is going away, and never delays or fails the run
        start_responder()
        for token in slots:
            KITS.pop(token, None)
            CSR_TOKENS.pop(token, None)
        if run_dir.is_dir():
            for child in run_dir.iterdir():
                if child.is_dir() or child.suffix == ".tgz":
                    shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink()
        run["end_time"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        run["state"] = final_state
        logger.info("Run %s: %s", run_id, final_state)


class SiteError(RuntimeError):
    """A site's task of a `FEDAVG` run failed, or printed no usable update: the run ends as `EXECUTOR_ERROR`."""


def wait_for_round(tasks: list[dict[str, Any]], timeout: float, size: int) -> list[fedavg.Update]:
    """Wait until all tasks of a round of a `FEDAVG` run are `COMPLETE`, reading each update as its task ends.

    Args:
        tasks: The tasks of the round.
        timeout: Seconds to wait.
        size: Number of weights of the model.

    Returns:
        The updates, in the order of the tasks.

    Raises:
        SiteError: A task ended otherwise, or printed no usable update; the
            others aren't waited for.
        TimeoutError: Not all tasks ended in time.
    """
    deadline = time.monotonic() + timeout
    updates: dict[int, fedavg.Update] = {}
    while True:
        # Terminal states of TES are final: only the others are asked for
        update_tasks({"tasks": [task for task in tasks if task["state"] not in TERMINAL_TES]})
        failed = [(task["site"], task["state"]) for task in tasks if task["state"] in TERMINAL_TES - {"COMPLETE"}]
        if failed:
            raise SiteError(f"Tasks failed in round {tasks[0]['round']}: {failed}")
        for number, task in enumerate(tasks):
            if task["state"] == "COMPLETE" and number not in updates:
                updates[number] = site_update(task, size)
        if len(updates) == len(tasks):
            return [updates[number] for number in range(len(tasks))]
        if time.monotonic() >= deadline:
            states = [(task["site"], task["state"]) for task in tasks]
            raise TimeoutError(f"Round {tasks[0]['round']} didn't end in time: {states}")
        time.sleep(2)


def site_update(task: dict[str, Any], size: int) -> fedavg.Update:
    """Get a site's update from the record of its task of a round, at its TES.

    Args:
        task: The task, `COMPLETE`.
        size: Number of weights of the model.

    Returns:
        The update.

    Raises:
        SiteError: The task's output has no usable update. The message says
            why, and doesn't echo the output.
    """
    reply = tes_request("GET", task["site"], f"{task['base']}/tasks/{task['id']}", params={"view": "FULL"}, timeout=30)
    reply.raise_for_status()
    try:
        return fedavg.parse_update(fedavg.task_stdout(reply.json()), size)
    except ValueError as error:
        raise SiteError(f"Update of {task['site']} in round {task['round']}: {error}") from None


def execute_fedavg(run_id: str, name: str, sites: list[str], rounds: int) -> None:
    """Carry out a run of `FEDAVG`, in the background: rounds of one TES task per site, averaged here.

    Nothing here listens for the tasks: each gets the model inline, and its
    update comes back through its record at the TES of its site
    (`wes/fedavg.py`). The FL port, and its probe responder, stay as they are.

    Args:
        run_id: Identifier of the run.
        name: Name of the workload.
        sites: Names of the sites.
        rounds: Number of rounds.
    """
    run = RUNS[run_id]
    final_state = "SYSTEM_ERROR"
    try:
        import numpy as np  # in the image; only this workflow type needs it

        run["state"] = "INITIALIZING"
        model = list(fedavg.workload(name).initial)
        run["state"] = "RUNNING"
        for round_ in range(1, rounds + 1):
            tasks: list[dict[str, Any]] = []
            for site in sites:
                base = tes_base(site)
                task = fedavg.site_task(run_id, site, round_, model, SITES[site]["data"], IMAGE, name)
                reply = tes_request("POST", site, f"{base}/tasks", json=pin_to_site(task, site), timeout=60)
                reply.raise_for_status()
                tasks.append({"site": site, "round": round_, "id": reply.json()["id"], "base": base, "state": "QUEUED"})
                run["tasks"].append(tasks[-1])
            model = fedavg.aggregate(wait_for_round(tasks, ROUND_TIMEOUT, len(model)))
            run["outputs"]["rounds_completed"] = round_
        run_dir = BASE / run_id
        run_dir.mkdir(parents=True)
        np.save(run_dir / "global_model.npy", np.asarray(model))
        run["outputs"]["global_model"] = f"/outputs/{run_id}/global_model.npy"
        final_state = "COMPLETE"
    except SiteError as error:
        logger.warning("Run %s failed at a site: %s", run_id, error)
        run["error"] = repr(error)
        final_state = "EXECUTOR_ERROR"
    except Exception as error:  # the run fails, the service stays
        logger.exception("Run %s failed", run_id)
        run["error"] = repr(error)
    finally:
        cancel_tasks(run)
        update_tasks({"tasks": [task for task in run["tasks"] if task["state"] not in TERMINAL_TES]}, wait=30)
        run["end_time"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        run["state"] = final_state
        logger.info("Run %s: %s", run_id, final_state)


_jwk_client: jwt.PyJWKClient | None = None


def jwk_client() -> jwt.PyJWKClient:
    """Get this process's JWKS client for `OIDC_ISSUER`, fetching its discovery document once.

    Returns:
        The client, caching the issuer's keys.

    Raises:
        ValueError: The issuer or the JWKS it names aren't reachable over https, and
            `WES_OIDC_ALLOW_HTTP` isn't set: an on-path attacker between the WES and
            the issuer could otherwise replace the discovery document or signing
            keys, and have forged tokens pass the checks that follow.
    """
    global _jwk_client
    if _jwk_client is None:
        if not OIDC_ALLOW_HTTP:
            tokens.check_url(OIDC_ISSUER, "WES_OIDC_ISSUER")
        discovery = requests.get(f"{OIDC_ISSUER.rstrip('/')}/.well-known/openid-configuration", timeout=10).json()
        jwks_uri = discovery["jwks_uri"]
        if not OIDC_ALLOW_HTTP:
            tokens.check_url(jwks_uri, "the issuer's jwks_uri")
        _jwk_client = jwt.PyJWKClient(jwks_uri)
    return _jwk_client


bearer = HTTPBearer(auto_error=False)


def authenticated(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> dict[str, Any]:
    """Check a caller's bearer token against `OIDC_ISSUER`.

    Args:
        credentials: The `Authorization` header, if the request has one.

    Returns:
        The token's claims.

    Raises:
        HTTPException: No issuer is configured, the token is missing, expired, or
            otherwise doesn't check out against it, or the issuer can't be reached
            to verify it.
    """
    if not OIDC_ISSUER:
        logger.warning("Auth: no trusted OIDC issuer is configured")
        raise HTTPException(401, "No trusted OIDC issuer is configured")
    if credentials is None:
        logger.warning("Auth: a caller sent no bearer token")
        raise HTTPException(401, "Bearer token required")
    try:
        key = jwk_client().get_signing_key_from_jwt(credentials.credentials).key
        return jwt.decode(
            credentials.credentials,
            key,
            algorithms=OIDC_ALGORITHMS,
            audience=OIDC_AUDIENCE,
            issuer=OIDC_ISSUER,
            options={"require": ["exp"]},
        )
    except jwt.InvalidTokenError as error:
        # PyJWT's messages name the failed check (expiry, audience, ...), never the token itself
        logger.warning("Auth: rejected a bearer token: %s", error)  # nosemgrep
        raise HTTPException(401, f"Invalid token: {error}") from None
    except Exception as error:  # noqa: BLE001 - a key with an unknown kid, or the issuer out of reach
        # Only the class of the error, never the token
        logger.warning("Auth: couldn't verify a bearer token: %s", type(error).__name__)  # nosemgrep
        raise HTTPException(503, "Can't reach the trusted issuer right now") from None


AUTH_DEPENDENCY = Depends(authenticated)


# A FLARE admin's name, safe to put in the hub's paths and commands
SAFE_ADMIN_NAME = re.compile(r"[A-Za-z0-9._@-]{1,80}")
# What NVFlare 2.9 itself accepts as an admin's name: an address, with the
# pattern of `nvflare.apis.utils.format_check` verbatim (its `|` included), and
# a name `nvflare cert request` takes as a certificate's common name, of at
# most 64 characters (`nvflare.tool.cert.cert_commands._validate_safe_cert_name`).
# The latter implies `SAFE_ADMIN_NAME`, which stays as the hub's own check,
# should NVFlare's ever loosen
NVFLARE_ADMIN_NAME = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}")
NVFLARE_CERT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@-]{0,63}")
# The domain of a derived admin name, when the issuer's host can't be one
DERIVED_ADMIN_DOMAIN = "subject.invalid"


class Identity(NamedTuple):
    """A caller's validated identity: `sub` to own runs by, `admin` to name the FLARE admin."""

    sub: str
    admin: str


def is_admin_name(name: str) -> bool:
    """Whether a name is safe for the hub and accepted by NVFlare as an admin's name.

    Args:
        name: The name.

    Returns:
        Whether it is.
    """
    return all(pattern.fullmatch(name) for pattern in (SAFE_ADMIN_NAME, NVFLARE_ADMIN_NAME, NVFLARE_CERT_NAME))


def admin_name_from_sub(sub: str) -> str:
    """Name the FLARE admin of a caller without a usable email, after its `sub`.

    LS Login access tokens, for one, carry no `email`, but their `sub` is an
    address already (`<40 hex>@lifescience-ri.eu`).

    Args:
        sub: The caller's subject.

    Returns:
        `sub` itself if it can name an admin; otherwise a deterministic name
        derived from it, `<first 32 hex of sha256(sub)>@<host of the trusted
        issuer>`, with the domain `subject.invalid` instead if that host can't
        name an admin either.
    """
    if is_admin_name(sub):
        return sub
    # `surrogatepass`: JSON can carry lone surrogates, which plain UTF-8 refuses
    digest = hashlib.sha256(sub.encode("utf-8", "surrogatepass")).hexdigest()[:32]
    derived = f"{digest}@{urllib.parse.urlsplit(OIDC_ISSUER).hostname or ''}"
    return derived if is_admin_name(derived) else f"{digest}@{DERIVED_ADMIN_DOMAIN}"


def identity(claims: dict[str, Any] = AUTH_DEPENDENCY) -> Identity:
    """The caller's identity: its `sub`, checked and allowed (H22), and its FLARE admin's name.

    Args:
        claims: The caller's validated claims.

    Returns:
        The identity: `sub`, to own runs by, and the FLARE admin's name for a
        run it starts: the token's `email`, or, if it has none or one that
        can't name an admin, a name from `sub` (`admin_name_from_sub`). Admin
        names aren't unique across subjects, and two subjects must never share
        ownership of a run through a shared or reassigned email, so `sub`, not
        the admin's name, is what run lookups are keyed on.

    Raises:
        HTTPException: The subject is missing or not a string, `WES_OIDC_ALLOWED_SUBS`
            is set and doesn't list it, or the email is not a string.
    """
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        logger.warning("Auth: a token had no 'sub' claim")
        raise HTTPException(400, "Bearer token is missing required 'sub' claim")
    if ALLOWED_SUBS and sub not in ALLOWED_SUBS:
        logger.warning("Auth: rejected disallowed subject %r", sub)
        raise HTTPException(403, "This identity isn't allowed to use this WES")
    email = claims.get("email")
    if email is None or email == "":
        admin = admin_name_from_sub(sub)
        # Debug only: the usual case for LS Login, and `identity` runs on every
        # request, polls included
        logger.debug("Auth: subject %r has no email claim; its FLARE admin is %r", sub, admin)
        return Identity(sub, admin)
    if not isinstance(email, str):
        logger.warning("Auth: subject %r has a non-string email claim", sub)
        raise HTTPException(400, "The submitter email must be a string")
    if not is_admin_name(email):
        # Unsafe, or one NVFlare would refuse only once the run has started
        admin = admin_name_from_sub(sub)
        logger.info("Auth: subject %r has an email claim that can't name a FLARE admin; it is %r", sub, admin)
        return Identity(sub, admin)
    return Identity(sub, email)


IDENTITY_DEPENDENCY = Depends(identity)


@app.get("/ga4gh/wes/v1/service-info")
def service_info() -> dict[str, Any]:
    """Describe the service.

    Returns:
        The service info of WES 1.1.
    """
    return {
        "id": "org.example.nvflare-thin-wes",
        "name": "Thin WES for NVFlare (sandbox)",
        "type": {"group": "org.ga4gh", "artifact": "wes", "version": "1.1.0"},
        "organization": {"name": "ELIXIR Cloud & AAI (sandbox)", "url": "https://elixir-cloud-aai.github.io"},
        "version": "0.0.0",
        "workflow_type_versions": {
            "NVFLARE": {"workflow_type_version": ["2.9"]},
            fedavg.WORKFLOW_TYPE: {"workflow_type_version": [fedavg.WORKFLOW_TYPE_VERSION]},
        },
        "supported_wes_versions": ["1.1.0"],
        "supported_filesystem_protocols": ["file"],
        "workflow_engine_versions": {"nvflare": {"workflow_engine_version": ["2.9.0"]}},
        "default_workflow_engine_parameters": [],
        "system_state_counts": {},
        "auth_instructions_url": (
            f"{OIDC_ISSUER.rstrip('/')}/.well-known/openid-configuration"
            if OIDC_ISSUER
            else "https://example.org/no-issuer-configured-auth-is-unavailable"
        ),
        "tags": {"sites": ",".join(SITES)},
    }


def job_sites(job_dir: pathlib.Path) -> int:
    """Read how many sites a FLARE job takes.

    The jobs here are built for an exact number of sites (`testset/job_src/job.py`):
    `min_clients` of the job, which is also `num_clients` of its FedAvg. With
    more sites, FedAvg would ask a random subset of them each round.

    Args:
        job_dir: Directory of the job.

    Returns:
        `min_clients` of the job's `meta.json`.

    Raises:
        HTTPException: The job doesn't say, as a positive whole number.
    """
    try:
        wanted = json.loads((job_dir / "meta.json").read_text()).get("min_clients")
    except (OSError, ValueError, AttributeError):
        wanted = None
    if isinstance(wanted, bool) or not isinstance(wanted, int) or wanted < 1:
        raise HTTPException(400, f"Job {job_dir.name} doesn't say how many sites it takes")
    return wanted


def available_jobs() -> list[str]:
    """List the FLARE jobs of the image.

    Returns:
        The names of the jobs, sorted.
    """
    return sorted(path.name for path in JOBS.iterdir())


@app.post("/ga4gh/wes/v1/runs")
def run_workflow(
    workflow_type: Annotated[str, Form(max_length=20)],
    workflow_type_version: Annotated[str, Form(max_length=20)],
    workflow_url: Annotated[str, Form(max_length=256)],
    workflow_params: Annotated[str, Form(max_length=8192)] = "{}",
    tags: Annotated[str, Form(max_length=8192)] = "{}",
    caller: Identity = IDENTITY_DEPENDENCY,
) -> dict[str, str]:
    """Start a run.

    Args:
        workflow_type: `NVFLARE`, or `FEDAVG` (`wes/fedavg.py`).
        workflow_type_version: `2.9` for `NVFLARE`, `1.0` for `FEDAVG`.
        workflow_url: Name of a job (`NVFLARE`) or of a workload (`FEDAVG`) in
            the image (no uploads, so no user code).
        workflow_params: JSON object, with the sites to use (`sites`, by
            default all), and for `FEDAVG` the number of rounds (`rounds`, by
            default 5). A job of `NVFLARE` takes exactly as many sites as its
            `min_clients` (`logreg-fedavg` two, `logreg-fedavg-<n>` n).
        tags: JSON object with tags of the run.
        caller: The caller's identity.

    Returns:
        The identifier of the run.

    Raises:
        HTTPException: The request is invalid, or another run is active.
    """
    try:
        params = json.loads(workflow_params)
    except ValueError:
        raise HTTPException(400, "workflow_params isn't valid JSON") from None
    if not isinstance(params, dict):
        raise HTTPException(400, "workflow_params isn't a JSON object")
    sites = params.get("sites", list(SITES))
    if not isinstance(sites, list) or not all(isinstance(site, str) for site in sites):
        raise HTTPException(400, f"sites must be a list of names; available: {sorted(SITES)}")
    if not sites or not set(sites) <= set(SITES):
        raise HTTPException(400, f"Unknown sites; available: {sorted(SITES)}")
    target: Any
    if (workflow_type, workflow_type_version) == ("NVFLARE", "2.9"):
        job_dir = (JOBS / workflow_url).resolve()
        if job_dir.parent != JOBS.resolve() or not job_dir.is_dir():
            raise HTTPException(400, f"Unknown job {workflow_url}; available: {available_jobs()}")
        # Each site once: a site is an FL client by its name, and FLARE has one client of a name.
        # Refused rather than dropped, so that the run's recorded request names the sites that ran
        if len(set(sites)) != len(sites):
            raise HTTPException(400, "Each site may be named only once")
        wanted = job_sites(job_dir)
        if len(sites) != wanted:
            raise HTTPException(
                400,
                f"Job {workflow_url} takes {wanted} sites, not {len(sites)}; name {wanted} sites"
                f" in workflow_params, or use a job for {len(sites)} if there is one (available: {available_jobs()})",
            )
        target, args = execute, (job_dir, sites, caller.admin)
    elif (workflow_type, workflow_type_version) == (fedavg.WORKFLOW_TYPE, fedavg.WORKFLOW_TYPE_VERSION):
        try:
            fedavg.workload(workflow_url)
            rounds = fedavg.parse_rounds(params)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
        # Each site once: a site named twice would count twice in the average
        target, args = execute_fedavg, (workflow_url, list(dict.fromkeys(sites)), rounds)
    else:
        raise HTTPException(
            400,
            f"Only workflow types NVFLARE, version 2.9, and {fedavg.WORKFLOW_TYPE},"
            f" version {fedavg.WORKFLOW_TYPE_VERSION}",
        )
    with LOCK:
        if any(r["state"] in ("QUEUED", "INITIALIZING", "RUNNING") for r in RUNS.values()):
            raise HTTPException(409, "Only one run at a time")
        run_id = str(uuid.uuid4())
        RUNS[run_id] = {
            "state": "QUEUED",
            # Runs are owned by `sub`: two subjects could share or swap an email
            "sub": caller.sub,
            "submitter": caller.admin,
            "request": {
                "workflow_type": workflow_type,
                "workflow_type_version": workflow_type_version,
                "workflow_url": workflow_url,
                "workflow_params": params,
                "tags": json.loads(tags),
            },
            "tasks": [],
            "outputs": {},
            "start_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    threading.Thread(target=target, args=(run_id, *args), daemon=True).start()
    return {"run_id": run_id}


def get_run(run_id: str, sub: str) -> dict[str, Any]:
    """Look up a run, if the caller is the one who started it.

    Args:
        run_id: Identifier of the run.
        sub: The caller's subject.

    Returns:
        The run.

    Raises:
        HTTPException: There is no such run, or it isn't this caller's own.
    """
    run = RUNS.get(run_id)
    if run is None or run["sub"] != sub:
        raise HTTPException(404, "No such run")
    return run


@app.get("/ga4gh/wes/v1/runs")
def list_runs(caller: Identity = IDENTITY_DEPENDENCY) -> dict[str, Any]:
    """List this caller's own runs.

    Args:
        caller: The caller's identity.

    Returns:
        Identifiers and states of the runs.
    """
    with LOCK:
        runs = list(RUNS.items())
    return {
        "runs": [
            {"run_id": key, "state": run["state"], "submitter": run["submitter"]}
            for key, run in runs
            if run["sub"] == caller.sub
        ],
        "next_page_token": "",
    }


@app.get("/ga4gh/wes/v1/runs/{run_id}/status")
def run_status(run_id: str, caller: Identity = IDENTITY_DEPENDENCY) -> dict[str, str]:
    """Get the state of a run.

    Args:
        run_id: Identifier of the run.
        caller: The caller's identity.

    Returns:
        Identifier and state of the run.
    """
    return {"run_id": run_id, "state": get_run(run_id, caller.sub)["state"]}


def task_name(task: dict[str, Any]) -> str:
    """Name a TES task in the run log.

    Args:
        task: The task of the run.

    Returns:
        Its name.
    """
    if "round" in task:
        return f"fedavg {task['site']} round {task['round']}"
    return "fl-server" if task["site"] == "server" else f"fl-client {task['site']}"


@app.get("/ga4gh/wes/v1/runs/{run_id}")
def run_log(run_id: str, caller: Identity = IDENTITY_DEPENDENCY) -> dict[str, Any]:
    """Get the log of a run.

    Args:
        run_id: Identifier of the run.
        caller: The caller's identity.

    Returns:
        The run log, with the TES tasks under `task_logs`.
    """
    run = get_run(run_id, caller.sub)
    if run["request"]["workflow_type"] == fedavg.WORKFLOW_TYPE:
        name, outputs = f"fedavg {run['request']['workflow_url']}", dict(run["outputs"])
    else:
        name = f"flare job {run.get('flare_job_id', '')}"
        outputs = dict(run["outputs"], flare_job_status=run.get("flare_job_status"))
    return {
        "run_id": run_id,
        "state": run["state"],
        "submitter": run["submitter"],
        "request": run["request"],
        "run_log": {
            "name": name,
            "start_time": run["start_time"],
            "end_time": run.get("end_time"),
            "system_logs": [run["error"]] if "error" in run else [],
        },
        "task_logs": [
            {"id": task["id"], "name": task_name(task), "system_logs": [task["state"]]} for task in run["tasks"]
        ],
        "outputs": outputs,
    }


@app.get("/kits/{token}/{name}")
def get_kit(token: str, name: str) -> FileResponse:
    """Serve the startup kit of a site, for as long as its run lasts.

    Args:
        token: Unguessable token of the kit.
        name: Name of the file.

    Returns:
        The kit.

    Raises:
        HTTPException: There is no such kit (any more).
    """
    archive = KITS.get(token)
    if archive is None or archive.name != name:
        raise HTTPException(404, "No such kit")
    return FileResponse(archive)


@app.post("/sites/{token}/csr")
async def sign_csr(token: str, request: Request) -> Response:
    """Sign a site's certificate signing request, as this run's CA (H4).

    Args:
        token: The site's one slot, from its TES task.
        request: Body is the site's `*.request.zip`, from `nvflare cert request`.

    Returns:
        The signed `*.signed.zip`, from `nvflare cert approve`.

    Raises:
        HTTPException: No such token, or the request isn't that site's own: a
            different name, a type other than a client's, or any role at all.
            Also, a request body over `MAX_CSR_SIZE`.
    """
    slot = CSR_TOKENS.get(token)
    if slot is None:
        raise HTTPException(404, "No such token")
    CSR_TOKENS.pop(token, None)  # Deleting token on use
    run_id, site = slot
    work = BASE / run_id / "csr" / token
    work.mkdir(parents=True)
    size = 0
    with (work / "request.zip").open("wb") as csr_file:
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_CSR_SIZE:
                raise HTTPException(413, "Certificate signing request too large")
            csr_file.write(chunk)
    result = await anyio.run_process(
        [
            "nvflare",
            "cert",
            "approve",
            "request.zip",
            "--ca-dir",
            "../../ca",
            "--profile",
            "../../project_profile.yaml",
            "--out",
            "signed.zip",
        ],
        cwd=work,
        check=True,
    )
    fields = parse_fields(result.stdout.decode("utf-8"))
    if (
        result.returncode != 0
        or fields.get("name") != site
        or fields.get("cert_type") != "client"
        or fields.get("cert_role") != "None"
    ):
        raise HTTPException(400, "The request doesn't match the site of this token")
    return Response((work / "signed.zip").read_bytes(), media_type="application/zip")


@app.get("/outputs/{run_id}/global_model.npy")
def get_model(run_id: str, caller: Identity = IDENTITY_DEPENDENCY) -> FileResponse:
    """Serve the global model of a run.

    Args:
        run_id: Identifier of the run.
        caller: The caller's identity.

    Returns:
        The model.

    Raises:
        HTTPException: There is no model, or the run isn't COMPLETE.
    """
    run = get_run(run_id, caller.sub)
    if run["state"] != "COMPLETE":
        raise HTTPException(404, "No model")
    path = BASE / run_id / "global_model.npy"
    if not path.is_file():
        raise HTTPException(404, "No model")
    return FileResponse(path)

"""A thin WES in front of NVFlare, with FL clients as TES tasks. Sandbox only.

Implements the part of the GA4GH WES 1.1 API that the testbed needs, for one
workflow type, `NVFLARE`. For each run it:

1. creates a root CA for that run alone, through `nvflare cert init`, and
   provisions the server and an admin itself, through `nvflare cert request`,
   `cert approve` and `package` run locally, one after another;
2. starts the FL server, by default as a child process of this service; with
   `FL_SERVER_MODE=tes`, as a TES task of its own (see `compose.server-task.yaml`);
3. submits one TES task per site, each running an FL client that makes its own
   key, sends this service a signing request over `/sites/{token}/csr`, and
   dials out to the server with the certificate that comes back;
4. submits the FLARE job through the FLARE admin API, and waits for it;
5. downloads the global model, shuts the federation down, deletes the CA.

Every shortcut in here is listed in `docs/testbed/shortcuts.md`. No
authentication, one run at a time, state in memory.
"""

import json
import logging
import os
import pathlib
import secrets
import shutil
import socket
import subprocess
import tarfile
import threading
import time
import uuid
from collections.abc import Mapping
from typing import Annotated, Any

import anyio
import requests
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, Response

from wes import tokens

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
    sources: dict[str, tokens.TokenSource] = {}
    for name, site in sites.items():
        source = tokens.from_site(name, site, environ)
        if source is None:
            continue
        if not str(site.get("tes", "")).startswith("https://"):
            raise ValueError(f"The token of site {name} only goes to a TES over https")
        sources[name] = source
    return sites, sources


SITES, TOKENS = load_sites(pathlib.Path(SITES_FILE).read_text() if SITES_FILE else os.environ.get("WES_SITES", "{}"))
# The sources hold the secrets now: child processes (`nvflare`, the FL server) don't inherit them
for _name in {name for source in TOKENS.values() for name in getattr(source, "env_names", ())}:
    os.environ.pop(_name, None)
# If set, tasks go to this gateway (proTES), pinned to the TES of the site by tag
TES_GATEWAY = os.environ.get("TES_GATEWAY_URL", "")
TES_GATEWAY_TOKEN_URL = os.environ.get("TES_GATEWAY_TOKEN_URL", "")
FL_SERVER_MODE = os.environ.get("FL_SERVER_MODE", "local")
FL_SERVER_TES = os.environ.get("FL_SERVER_TES", "")
# `grpc` or `http`, the latter (WebSocket) for sites that only allow port 443 out
FL_SCHEME = os.environ.get("FL_SCHEME", "grpc")
FL_PORT = int(os.environ.get("FL_PORT", "8002"))
ORG = "testbed"
ADMIN = "admin@testbed.invalid"
ADMIN_PORT = 8003
START_TIMEOUT = 180
JOB_TIMEOUT = 600
MAX_CSR_SIZE = 1 << 20  # a CSR package is a few KB; this just bounds memory
TERMINAL_TES = {"COMPLETE", "EXECUTOR_ERROR", "SYSTEM_ERROR", "CANCELED", "PREEMPTED"}

app = FastAPI(title="Thin WES for NVFlare (sandbox)")
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
    """Get the token source of a site, if its token goes anywhere.

    Args:
        site: Name of the site, or `server` for the task of the FL server.

    Returns:
        The source, or `None` if the site has none, or there's a gateway: the
        token of a site is for its TES alone, and never goes to a gateway.
    """
    return None if TES_GATEWAY_TOKEN_URL or TES_GATEWAY else TOKENS.get(site)


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
        token = requests.get(TES_GATEWAY_TOKEN_URL, timeout=10).json()["access_token"]
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
        renewed = tes_headers(site)
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
    if TES_GATEWAY:
        task["tags"]["gateway.backends"] = json.dumps({"type": "allow", "backends": [SITES[site]["tes"]]})
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
                logger.warning("No token for the TES of %s: %s", task["site"], error)
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


def execute(run_id: str, job_dir: pathlib.Path, sites: list[str]) -> None:
    """Carry out a run, in the background.

    Args:
        run_id: Identifier of the run.
        job_dir: Directory of the FLARE job.
        sites: Names of the sites.
    """
    from nvflare.fuel.flare_api.flare_api import new_secure_session

    run = RUNS[run_id]
    run_dir = BASE / run_id
    run_dir.mkdir(parents=True)
    server: subprocess.Popen[bytes] | None = None
    slots: list[str] = []
    final_state = "SYSTEM_ERROR"
    try:
        run["state"] = "INITIALIZING"
        project = f"run{run_id[:8]}"
        fingerprint = init_ca(run_dir, project)
        server_kit = provision_locally(run_dir, project, FL_HOST, "server")
        admin_kit = provision_locally(run_dir, project, ADMIN, "admin")
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
        for site in sites:
            token, csr_url = issue_csr_token(run_id, site)
            slots.append(token)
            base = tes_base(site)
            reply = tes_request(
                "POST", site, f"{base}/tasks", json=client_task(run_id, site, project, csr_url, fingerprint), timeout=60
            )
            reply.raise_for_status()
            run["tasks"].append({"site": site, "id": reply.json()["id"], "base": base, "state": "QUEUED"})
        session = new_secure_session(ADMIN, str(admin_kit), timeout=60)
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
        for token in slots:
            KITS.pop(token, None)
            CSR_TOKENS.pop(token, None)
        for child in run_dir.iterdir():
            if child.is_dir() or child.suffix == ".tgz":
                shutil.rmtree(child, ignore_errors=True) if child.is_dir() else child.unlink()
        run["end_time"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        run["state"] = final_state
        logger.info("Run %s: %s", run_id, final_state)


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
        "workflow_type_versions": {"NVFLARE": {"workflow_type_version": ["2.9"]}},
        "supported_wes_versions": ["1.1.0"],
        "supported_filesystem_protocols": ["file"],
        "workflow_engine_versions": {"nvflare": {"workflow_engine_version": ["2.9.0"]}},
        "default_workflow_engine_parameters": [],
        "system_state_counts": {},
        "auth_instructions_url": "https://example.org/no-auth-this-is-a-sandbox",
        "tags": {"sites": ",".join(SITES)},
    }


@app.post("/ga4gh/wes/v1/runs")
def run_workflow(
    workflow_type: Annotated[str, Form()],
    workflow_type_version: Annotated[str, Form()],
    workflow_url: Annotated[str, Form()],
    workflow_params: Annotated[str, Form()] = "{}",
    tags: Annotated[str, Form()] = "{}",
) -> dict[str, str]:
    """Start a run.

    Args:
        workflow_type: Must be `NVFLARE`.
        workflow_type_version: Must be `2.9`.
        workflow_url: Name of a job in the image (no uploads, so no user code).
        workflow_params: JSON object, with the sites to use (`sites`).
        tags: JSON object with tags of the run.

    Returns:
        The identifier of the run.

    Raises:
        HTTPException: The request is invalid, or another run is active.
    """
    if workflow_type != "NVFLARE" or workflow_type_version != "2.9":
        raise HTTPException(400, "Only workflow type NVFLARE, version 2.9")
    job_dir = (JOBS / workflow_url).resolve()
    if job_dir.parent != JOBS.resolve() or not job_dir.is_dir():
        raise HTTPException(400, f"Unknown job {workflow_url}; available: {sorted(p.name for p in JOBS.iterdir())}")
    params = json.loads(workflow_params)
    sites = params.get("sites", list(SITES))
    if not sites or not set(sites) <= set(SITES):
        raise HTTPException(400, f"Unknown sites; available: {sorted(SITES)}")
    with LOCK:
        if any(r["state"] in ("QUEUED", "INITIALIZING", "RUNNING") for r in RUNS.values()):
            raise HTTPException(409, "Only one run at a time")
        run_id = str(uuid.uuid4())
        RUNS[run_id] = {
            "state": "QUEUED",
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
    threading.Thread(target=execute, args=(run_id, job_dir, sites), daemon=True).start()
    return {"run_id": run_id}


def get_run(run_id: str) -> dict[str, Any]:
    """Look up a run.

    Args:
        run_id: Identifier of the run.

    Returns:
        The run.

    Raises:
        HTTPException: There is no such run.
    """
    if run_id not in RUNS:
        raise HTTPException(404, "No such run")
    return RUNS[run_id]


@app.get("/ga4gh/wes/v1/runs")
def list_runs() -> dict[str, Any]:
    """List the runs.

    Returns:
        Identifiers and states of the runs.
    """
    return {"runs": [{"run_id": key, "state": run["state"]} for key, run in RUNS.items()], "next_page_token": ""}


@app.get("/ga4gh/wes/v1/runs/{run_id}/status")
def run_status(run_id: str) -> dict[str, str]:
    """Get the state of a run.

    Args:
        run_id: Identifier of the run.

    Returns:
        Identifier and state of the run.
    """
    return {"run_id": run_id, "state": get_run(run_id)["state"]}


def task_name(task: dict[str, str]) -> str:
    """Name a TES task in the run log.

    Args:
        task: The task of the run.

    Returns:
        Its name.
    """
    return "fl-server" if task["site"] == "server" else f"fl-client {task['site']}"


@app.get("/ga4gh/wes/v1/runs/{run_id}")
def run_log(run_id: str) -> dict[str, Any]:
    """Get the log of a run.

    Args:
        run_id: Identifier of the run.

    Returns:
        The run log, with the TES tasks under `task_logs`.
    """
    run = get_run(run_id)
    return {
        "run_id": run_id,
        "state": run["state"],
        "request": run["request"],
        "run_log": {
            "name": f"flare job {run.get('flare_job_id', '')}",
            "start_time": run["start_time"],
            "end_time": run.get("end_time"),
            "system_logs": [run["error"]] if "error" in run else [],
        },
        "task_logs": [
            {"id": task["id"], "name": task_name(task), "system_logs": [task["state"]]} for task in run["tasks"]
        ],
        "outputs": dict(run["outputs"], flare_job_status=run.get("flare_job_status")),
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
def get_model(run_id: str) -> FileResponse:
    """Serve the global model of a run.

    Args:
        run_id: Identifier of the run.

    Returns:
        The model.

    Raises:
        HTTPException: There is no model.
    """
    get_run(run_id)
    path = BASE / run_id / "global_model.npy"
    if not path.is_file():
        raise HTTPException(404, "No model")
    return FileResponse(path)

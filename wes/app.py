"""A thin WES in front of NVFlare, with FL clients as TES tasks. Sandbox only.

Implements the part of the GA4GH WES 1.1 API that the testbed needs, for one
workflow type, `NVFLARE`. For each run it:

1. provisions a federation for that run alone (fresh CA, kits for the server,
   the sites and an admin);
2. starts the FL server, by default as a child process of this service; with
   `FL_SERVER_MODE=tes`, as a TES task of its own (see `compose.server-task.yaml`);
3. submits one TES task per site, each running an FL client that dials out to
   the server, with the kit and the site's data as inputs of the task;
4. submits the FLARE job through the FLARE admin API, and waits for it;
5. downloads the global model, shuts the federation down, deletes the kits.

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
from typing import Annotated, Any

import requests
from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import FileResponse

logger = logging.getLogger("wes")

BASE = pathlib.Path(os.environ.get("WES_WORKDIR", "/tmp/wes"))
PUBLIC_URL = os.environ.get("WES_INTERNAL_URL", "http://fl-hub:8080")
FL_HOST = os.environ.get("FL_SERVER_NAME", "fl-hub")
IMAGE = os.environ.get("FL_IMAGE", "nvflare-testbed:local")
JOBS = pathlib.Path(os.environ.get("FL_JOBS", "/app/testset/job"))
# {"site-1": {"tes": "http://funnel-site-1:8000", "data": "file:///data/site-1.csv"}, ...}
SITES: dict[str, dict[str, str]] = json.loads(os.environ.get("WES_SITES", "{}"))
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
TERMINAL_TES = {"COMPLETE", "EXECUTOR_ERROR", "SYSTEM_ERROR", "CANCELED", "PREEMPTED"}

app = FastAPI(title="Thin WES for NVFlare (sandbox)")
RUNS: dict[str, dict[str, Any]] = {}
KITS: dict[str, pathlib.Path] = {}
LOCK = threading.Lock()


PROJECT = """\
api_version: 3
name: {name}
description: Federation of one WES run
participants:
  - name: {host}
    type: server
    org: {org}
    fed_learn_port: {fl_port}
    admin_port: {admin_port}
{clients}
  - name: {admin}
    type: admin
    org: {org}
    role: project_admin
builders:
  - path: nvflare.lighter.impl.workspace.WorkspaceBuilder
  - path: nvflare.lighter.impl.static_file.StaticFileBuilder
    args:
      config_folder: config
      scheme: {scheme}
  - path: nvflare.lighter.impl.cert.CertBuilder
    args:
      root_valid_days: 2
  - path: nvflare.lighter.impl.signature.SignatureBuilder
"""


def provision(run_dir: pathlib.Path, name: str, sites: list[str]) -> pathlib.Path:
    """Create the federation of a run, with a CA of its own.

    Args:
        run_dir: Working directory of the run.
        name: Name of the federation.
        sites: Names of the sites.

    Returns:
        The directory with the startup kits.
    """
    clients = "\n".join(f"  - name: {site}\n    type: client\n    org: {ORG}" for site in sites)
    project = run_dir / "project.yml"
    project.write_text(
        PROJECT.format(
            name=name,
            host=FL_HOST,
            org=ORG,
            fl_port=FL_PORT,
            scheme=FL_SCHEME,
            admin_port=ADMIN_PORT,
            clients=clients,
            admin=ADMIN,
        )
    )
    subprocess.run(
        ["nvflare", "provision", "-p", str(project), "-w", str(run_dir / "workspace"), "--force"],
        check=True,
        capture_output=True,
    )
    return run_dir / "workspace" / name / "prod_00"


def start_server(kits: pathlib.Path, log_path: pathlib.Path) -> subprocess.Popen[bytes]:
    """Start the FL server as a child process.

    Args:
        kits: Directory with the startup kits.
        log_path: File for the output of the server.

    Returns:
        The process.
    """
    kit = kits / FL_HOST
    with log_path.open("wb") as log:
        return subprocess.Popen(
            [
                "python3",
                "-u",
                "-m",
                "nvflare.private.fed.app.server.server_train",
                "-m",
                str(kit),
                "-s",
                "fed_server.json",
                "--set",
                "secure_train=true",
                f"org={ORG}",
                "config_folder=config",
            ],
            cwd=kit,
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


def publish_kit(kits: pathlib.Path, site: str, run_dir: pathlib.Path) -> tuple[str, str]:
    """Pack the kit of a site, and serve it under an unguessable path.

    Args:
        kits: Directory with the startup kits.
        site: Name of the site.
        run_dir: Working directory of the run.

    Returns:
        The token of the kit and its URL.
    """
    token = secrets.token_urlsafe(32)
    archive = run_dir / f"{site}.tgz"
    with tarfile.open(archive, "w:gz") as tar:
        for entry in (kits / site).iterdir():
            tar.add(entry, arcname=entry.name)
    KITS[token] = archive
    return token, f"{PUBLIC_URL}/kits/{token}/{site}.tgz"


def tes_headers() -> dict[str, str]:
    """Get the headers for the TES gateway.

    Returns:
        The headers: an access token if the gateway needs one, else none.
    """
    if not TES_GATEWAY_TOKEN_URL:
        return {}
    token = requests.get(TES_GATEWAY_TOKEN_URL, timeout=10).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def tes_base(site: str) -> str:
    """Get the base URL to submit the tasks of a site to.

    Args:
        site: Name of the site.

    Returns:
        The URL of the gateway if there is one, else of the TES of the site.
    """
    return f"{TES_GATEWAY or SITES[site]['tes']}/ga4gh/tes/v1"


def client_task(run_id: str, site: str, kit_url: str) -> dict[str, Any]:
    """Build the TES task of an FL client.

    Args:
        run_id: Identifier of the run.
        site: Name of the site.
        kit_url: URL of the site's startup kit.

    Returns:
        The task. The data of the site is named by a URL that only resolves at
        the site: it never passes through this service.
    """
    task: dict[str, Any] = {
        "name": f"fl-client-{site}-{run_id[:8]}",
        "description": "NVFlare client of a WES run (sandbox)",
        "inputs": [
            {"name": "kit", "url": kit_url, "path": "/kit/kit.tgz", "type": "FILE"},
            {"name": "data", "url": SITES[site]["data"], "path": f"/data/{site}.csv", "type": "FILE"},
        ],
        "executors": [
            {
                "image": IMAGE,
                "command": ["fl-client", site, ORG, "/kit/kit.tgz"],
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
            reply = requests.get(
                f"{task['base']}/tasks/{task['id']}", params={"view": "MINIMAL"}, headers=tes_headers(), timeout=30
            )
            if reply.ok:
                task["state"] = reply.json().get("state", "UNKNOWN")
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
            requests.post(f"{task['base']}/tasks/{task['id']}:cancel", headers=tes_headers(), timeout=30)


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
    tokens: list[str] = []
    final_state = "SYSTEM_ERROR"
    try:
        run["state"] = "INITIALIZING"
        kits = provision(run_dir, f"run{run_id[:8]}", sites)
        if FL_SERVER_MODE == "tes":
            token, kit_url = publish_kit(kits, FL_HOST, run_dir)
            tokens.append(token)
            base = f"{FL_SERVER_TES}/ga4gh/tes/v1"
            reply = requests.post(f"{base}/tasks", json=server_task(run_id, kit_url), timeout=60)
            reply.raise_for_status()
            run["tasks"].append({"site": "server", "id": reply.json()["id"], "base": base, "state": "QUEUED"})
            wait_for_port(FL_HOST, ADMIN_PORT, START_TIMEOUT)
        else:
            server = start_server(kits, run_dir / "server.log")
            wait_for_port("127.0.0.1", ADMIN_PORT, START_TIMEOUT)
        for site in sites:
            token, kit_url = publish_kit(kits, site, run_dir)
            tokens.append(token)
            base = tes_base(site)
            reply = requests.post(
                f"{base}/tasks", json=client_task(run_id, site, kit_url), headers=tes_headers(), timeout=60
            )
            reply.raise_for_status()
            run["tasks"].append({"site": site, "id": reply.json()["id"], "base": base, "state": "QUEUED"})
        session = new_secure_session(ADMIN, str(kits / ADMIN), timeout=60)
        try:
            run["state"] = "RUNNING"
            wait_for_clients(session, run, sites, START_TIMEOUT)
            job_id = session.submit_job(str(job_dir))
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
        for token in tokens:
            KITS.pop(token, None)
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

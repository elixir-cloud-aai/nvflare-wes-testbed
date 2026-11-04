"""One WES run end to end, with checks of the outcome: test T2 of the docs."""

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

import requests

WES = os.environ["WES_URL"]
TIMEOUT = 600
TERMINAL = {"COMPLETE", "EXECUTOR_ERROR", "SYSTEM_ERROR", "CANCELED"}
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: object = "") -> None:
    """Record a check and print it.

    Args:
        name: What is checked.
        passed: Whether it holds.
        detail: What to print along with it.
    """
    RESULTS.append((name, passed, str(detail)))
    print(f"[{'ok' if passed else 'FAIL'}] {name}: {detail}", flush=True)


def main() -> None:
    """Submit a run, wait for it, and check what came out."""
    info = requests.get(f"{WES}/service-info", timeout=30).json()
    check("WES serves NVFLARE", "NVFLARE" in info["workflow_type_versions"], info["workflow_type_versions"])
    reply = requests.post(
        f"{WES}/runs",
        data={
            "workflow_type": "NVFLARE",
            "workflow_type_version": "2.9",
            "workflow_url": "logreg-fedavg",
            "workflow_params": json.dumps({"sites": ["site-1", "site-2"]}),
        },
        timeout=30,
    )
    reply.raise_for_status()
    run_id = reply.json()["run_id"]
    print(f"run {run_id}", flush=True)

    start = time.monotonic()
    state = ""
    while time.monotonic() - start < TIMEOUT:
        new = requests.get(f"{WES}/runs/{run_id}/status", timeout=30).json()["state"]
        if new != state:
            state = new
            print(f"{time.monotonic() - start:5.0f} s  {state}", flush=True)
        if state in TERMINAL:
            break
        time.sleep(2)
    log = requests.get(f"{WES}/runs/{run_id}", timeout=30).json()
    print(json.dumps(log, indent=2), flush=True)
    check("run is COMPLETE", state == "COMPLETE", state)
    check("FLARE job finished", log["outputs"].get("flare_job_status") == "FINISHED:COMPLETED", log["outputs"])
    check(
        "one TES task per site, all COMPLETE",
        len(log["task_logs"]) >= 2 and all(t["system_logs"] == ["COMPLETE"] for t in log["task_logs"]),
        [(t["name"], t["system_logs"]) for t in log["task_logs"]],
    )

    base = WES.split("/ga4gh")[0]
    model = requests.get(f"{base}/outputs/{run_id}/global_model.npy", timeout=30)
    check("global model can be downloaded", model.status_code == 200, f"{len(model.content)} bytes")
    if model.status_code == 200:
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "model.npy"
            path.write_bytes(model.content)
            done = subprocess.run(
                [sys.executable, "/app/testset/evaluate.py", str(path), "--data", "/testset-data"],
                capture_output=True,
                text=True,
                check=False,
            )
            check("federated model beats both local ones", done.returncode == 0, (done.stdout + done.stderr).strip())

    # The kit's URL is in the record of the TES task (hack H3): it must be dead by now
    site_tes = {"fl-client site-1": "http://funnel-site-1:8000", "fl-client site-2": "http://funnel-site-2:8000"}
    gateway = os.environ.get("TES_GATEWAY_URL", "")
    headers = {}
    if gateway:
        token = requests.get(os.environ["TES_GATEWAY_TOKEN_URL"], timeout=30).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
    for task in log["task_logs"]:
        if task["name"] not in site_tes:
            continue
        full = requests.get(
            # Plain HTTP on the private network of the testbed (hack H7)
            # nosemgrep: python.lang.security.audit.insecure-transport.requests.request-with-http.request-with-http
            f"{gateway or site_tes[task['name']]}/ga4gh/tes/v1/tasks/{task['id']}",
            params={"view": "FULL"},
            headers=headers,
            timeout=30,
        ).json()
        kit_url = next(entry["url"] for entry in full["inputs"] if entry["name"] == "kit")
        # Plain HTTP on the private network of the testbed (hack H7)
        # nosemgrep: python.lang.security.audit.insecure-transport.requests.request-with-http.request-with-http
        status = requests.get(kit_url, timeout=30).status_code
        check(f"kit link of {task['name']} is dead after the run", status == 404, status)
        data_prefix = os.environ.get("EXPECTED_DATA_PREFIX", "")
        if data_prefix:
            data_url = next(entry["url"] for entry in full["inputs"] if entry["name"] == "data")
            check(f"{task['name']} fetched its data from the public URL", data_url.startswith(data_prefix), data_url)
        if gateway:
            backend = full["tags"].get("gateway.backend")
            check(f"{task['name']} ran at the TES of its site", backend == site_tes[task["name"]], backend)

    failed = [name for name, passed, _ in RESULTS if not passed]
    print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

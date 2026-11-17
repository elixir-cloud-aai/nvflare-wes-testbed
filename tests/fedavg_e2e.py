"""One plain FedAvg run end to end, with checks of the outcome: test T10 of the docs.

As T2 (`tests/e2e.py`), but with workflow type `FEDAVG`: no NVFlare, no FL
port, rounds of one TES task per site, averaged by the WES (`wes/fedavg.py`).
"""

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

import requests
from oidc_test_token import header

WES = os.environ["WES_URL"]
AUTH = header()
ROUNDS = 5
TIMEOUT = 600
TERMINAL = {"COMPLETE", "EXECUTOR_ERROR", "SYSTEM_ERROR", "CANCELED"}
# Plain HTTP on the private network of the testbed (hack H7)
SITE_TES = {"site-1": "http://funnel-site-1:8000", "site-2": "http://funnel-site-2:8000"}
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


def submit(workflow_url: str = "logreg", **params: object) -> requests.Response:
    """Ask the WES for a `FEDAVG` run of both sites.

    Args:
        workflow_url: Name of the workload.
        **params: More `workflow_params`.

    Returns:
        The reply.
    """
    return requests.post(
        f"{WES}/runs",
        data={
            "workflow_type": "FEDAVG",
            "workflow_type_version": "1.0",
            "workflow_url": workflow_url,
            "workflow_params": json.dumps({"sites": ["site-1", "site-2"], **params}),
        },
        headers=AUTH,
        timeout=30,
    )


def main() -> None:
    """Refuse bad requests, submit a run, wait for it, and check what came out."""
    info = requests.get(f"{WES}/service-info", timeout=30).json()
    check("WES serves FEDAVG", "FEDAVG" in info["workflow_type_versions"], info["workflow_type_versions"])
    for name, reply in {
        "an unknown workload": submit("logreg-fedavg"),
        "a workload by path": submit("../fedavg/site_round.py"),
        "zero rounds": submit(rounds=0),
        "too many rounds": submit(rounds=1000),
    }.items():
        check(f"{name} is refused", reply.status_code == 400, reply.status_code)

    started = time.monotonic()
    reply = submit(rounds=ROUNDS)
    reply.raise_for_status()
    run_id = reply.json()["run_id"]
    print(f"run {run_id}", flush=True)
    state = ""
    while time.monotonic() - started < TIMEOUT:
        new = requests.get(f"{WES}/runs/{run_id}/status", headers=AUTH, timeout=30).json()["state"]
        if new != state:
            state = new
            print(f"{time.monotonic() - started:5.0f} s  {state}", flush=True)
        if state in TERMINAL:
            break
        time.sleep(2)
    log = requests.get(f"{WES}/runs/{run_id}", headers=AUTH, timeout=30).json()
    print(json.dumps(log, indent=2), flush=True)
    check("run is COMPLETE", state == "COMPLETE", f"{state} after {time.monotonic() - started:.0f} s")
    check("all rounds done", log["outputs"].get("rounds_completed") == ROUNDS, log["outputs"])
    expected = [f"fedavg {site} round {r}" for r in range(1, ROUNDS + 1) for site in ("site-1", "site-2")]
    check(
        "one TES task per site and round, all COMPLETE",
        [t["name"] for t in log["task_logs"]] == expected
        and all(t["system_logs"] == ["COMPLETE"] for t in log["task_logs"]),
        [(t["name"], t["system_logs"]) for t in log["task_logs"]],
    )

    base = WES.split("/ga4gh")[0]
    model = requests.get(f"{base}/outputs/{run_id}/global_model.npy", headers=AUTH, timeout=30)
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

    # What a site's TES keeps of a round: the model in, the update out, and nothing that opens anything
    hub = base.split("://", 1)[1].split(":")[0]
    for task in log["task_logs"][:2]:
        site = task["name"].split()[1]
        full = requests.get(
            # nosemgrep: python.lang.security.audit.insecure-transport.requests.request-with-http.request-with-http
            f"{SITE_TES[site]}/ga4gh/tes/v1/tasks/{task['id']}",
            params={"view": "FULL"},
            timeout=30,
        ).json()
        record = json.dumps({key: full.get(key) for key in ("inputs", "outputs", "executors", "tags")})
        check(f"{task['name']} ran at the TES of its site", full.get("tags", {}).get("site") == site, full.get("tags"))
        check(f"{task['name']} names no hub, link or token", hub not in record and "token" not in record.lower())
        # Funnel reports an inline input with an empty URL
        urls = [entry["url"] for entry in full["inputs"] if entry.get("url")]
        check(f"{task['name']} fetches nothing but its data", urls == [f"file:///data/{site}.csv"], urls)
        stdout = full["logs"][-1]["logs"][-1].get("stdout", "")
        check(f"{task['name']} printed its update", "FEDAVG_UPDATE " in stdout, stdout.strip()[:80])

    failed = [name for name, passed, _ in RESULTS if not passed]
    print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

"""Submit the probe task to a TES, or through proTES, and print what it found.

See "Probing a node" in `docs/setup/real-sites.md`. A token for the TES, if it
needs one, comes from the environment variable `TES_TOKEN`, so that it stays out
of command lines. Ends with 0 if the node can take part: a port was open, and the
task got its input and environment, and could write to `/tmp`.
"""

import argparse
import json
import os
import sys
import time
from typing import Any

import requests

RESULT_PREFIX = "PROBE-RESULT "
TERMINAL = {"COMPLETE", "EXECUTOR_ERROR", "SYSTEM_ERROR", "CANCELED", "PREEMPTED"}
IMAGE = "elixircloud/nvflare-wes-testbed:dev"
# The first site's share of the synthetic test set; see docs/setup/real-sites.md
INPUT_URL = (
    "https://raw.githubusercontent.com/elixir-cloud-aai/nvflare-wes-testbed/"
    "b473b4b2d3246d6b5f74c31e209268e0c093e062/testset/data/site-1.csv"
)
INPUT_SHA256 = "c578295a4bd973bb98fa2def75cffd50313dd9c7ab6b34f6548124a70103c001"
INPUT_PATH = "/probe/input.csv"


def parse_arguments() -> argparse.Namespace:
    """Parse the command line.

    Returns:
        The arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tes", required=True, help="Base URL of the TES or proTES, without /ga4gh/tes/v1")
    parser.add_argument("--backend", help="Through proTES: base URL of the TES to pin the task to")
    parser.add_argument("--hub", required=True, help="Name or address of the hub")
    parser.add_argument("--ports", default="8002,443", help="Ports of the hub to try, separated by commas")
    parser.add_argument("--image", default=IMAGE, help="Image of the task, which must be the testbed's")
    parser.add_argument("--timeout", type=int, default=600, help="Seconds to wait for the task")
    return parser.parse_args()


def build_task(args: argparse.Namespace) -> dict[str, Any]:
    """Build the probe task.

    Args:
        args: The command line arguments.

    Returns:
        The TES task.
    """
    targets = [f"{args.hub}:{port.strip()}" for port in args.ports.split(",")]
    tags = {"purpose": "nvflare-wes-testbed-probe"}
    if args.backend:
        tags["gateway.backends"] = json.dumps({"type": "allow", "backends": [args.backend]})
    return {
        "name": "nvflare-wes-testbed-probe",
        "description": "What a task may do at this node (sandbox, synthetic data only)",
        "inputs": [{"name": "probe-input", "url": INPUT_URL, "path": INPUT_PATH, "type": "FILE"}],
        "executors": [
            {
                "image": args.image,
                "command": ["python3", "/app/tests/probe.py", "node", INPUT_PATH, INPUT_SHA256, *targets],
                "env": {"PROBE_ENV": "passed", "HOME": "/tmp"},
            }
        ],
        "resources": {"cpu_cores": 1, "ram_gb": 0.5, "disk_gb": 0.5},
        "tags": tags,
    }


def wait_for_task(url: str, task_id: str, headers: dict[str, str], timeout: int) -> dict[str, Any]:
    """Wait until a task has ended, and cancel it if that takes too long.

    Args:
        url: Base URL of the TES API.
        task_id: Identifier of the task.
        headers: Headers of the requests.
        timeout: Seconds to wait.

    Returns:
        The full record of the task.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        reply = requests.get(f"{url}/tasks/{task_id}", params={"view": "MINIMAL"}, headers=headers, timeout=30)
        reply.raise_for_status()
        if reply.json().get("state") in TERMINAL:
            break
        time.sleep(3)
    else:
        requests.post(f"{url}/tasks/{task_id}:cancel", headers=headers, timeout=30)
    reply = requests.get(f"{url}/tasks/{task_id}", params={"view": "FULL"}, headers=headers, timeout=30)
    reply.raise_for_status()
    return reply.json()


def find_result(task: dict[str, Any]) -> dict[str, Any] | None:
    """Find the findings of the probe in the record of a task.

    Args:
        task: The full record of the task.

    Returns:
        The findings, or nothing if the log doesn't hold them.
    """
    for attempt in task.get("logs") or []:
        for executor in attempt.get("logs") or []:
            for line in (executor.get("stdout") or "").splitlines():
                if line.startswith(RESULT_PREFIX):
                    return json.loads(line.removeprefix(RESULT_PREFIX))
    return None


def read_from_backend(task: dict[str, Any], args: argparse.Namespace, headers: dict[str, str]) -> dict[str, Any] | None:
    """Find the findings at the TES behind a gateway, as proTES keeps no task output.

    Args:
        task: The full record of the task at the gateway.
        args: The command line arguments.
        headers: Headers of the requests, which only go to the TES named with `--backend`.

    Returns:
        The findings, or nothing if there's no such TES, or it doesn't hold them.
    """
    tags = task.get("tags") or {}
    backend, backend_id = tags.get("gateway.backend"), tags.get("gateway.backend_task_id")
    if not backend or not backend_id:
        return None
    reply = requests.get(
        f"{backend.rstrip('/')}/ga4gh/tes/v1/tasks/{backend_id}",
        params={"view": "FULL"},
        headers=headers if backend == args.backend else {},
        timeout=30,
    )
    return find_result(reply.json()) if reply.ok else None


def can_take_part(result: dict[str, Any]) -> bool:
    """Tell whether a node has what a client needs.

    Args:
        result: The findings of the probe.

    Returns:
        Whether a port was open, and the input, environment and `/tmp` work.
    """
    return (
        "open" in result["targets"].values()
        and result["input"] == "ok"
        and result["env_passed"]
        and result["tmp_writable"]
    )


def main() -> None:
    """Submit the task, wait for it, and print the outcome."""
    args = parse_arguments()
    url = f"{args.tes.rstrip('/')}/ga4gh/tes/v1"
    token = os.environ.get("TES_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    reply = requests.post(f"{url}/tasks", json=build_task(args), headers=headers, timeout=60)
    reply.raise_for_status()
    task_id = reply.json()["id"]
    print(f"Task {task_id}", flush=True)
    task = wait_for_task(url, task_id, headers, args.timeout)
    print(f"State: {task.get('state')}")
    result = find_result(task) or read_from_backend(task, args, headers)
    if result is None:
        print("No findings in the log of the task. Ask the operator of the node for it, or why it failed.")
        print("[FAIL] the node can't take part, as far as this shows")
        sys.exit(1)
    for target, outcome in result["targets"].items():
        print(f"Port {target}: {outcome}")
    for key in ("input", "env_passed", "uid", "gid", "tmp_writable", "root_writable"):
        print(f"{key}: {result[key]}")
    if not can_take_part(result):
        print("[FAIL] the node can't take part: see above")
        sys.exit(1)
    print("[ok] the node can take part")


if __name__ == "__main__":
    main()

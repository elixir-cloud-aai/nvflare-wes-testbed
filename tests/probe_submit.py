"""Submit the probe task to a TES, or through proTES, and print what it found.

See "Probing a node" in `docs/setup/real-sites.md`. A token for the TES, if it
needs one, comes from the environment variable `TES_TOKEN`, so that it stays out
of command lines.

Ends with 0 if the node can take part: the task completed, reached the FL port of
the hub, got its input and environment, and could write to `/tmp`. Ends with 1 if
it can't, and with 2 if this doesn't tell: nothing listened on the FL port, the
log isn't in the record, or the task ran elsewhere than asked for.
"""

import argparse
import json
import os
import sys
import time
from typing import Any

import requests

RESULT_PREFIX = "PROBE-RESULT "
EXIT_CANNOT = 1
EXIT_INCONCLUSIVE = 2
TERMINAL = {"COMPLETE", "EXECUTOR_ERROR", "SYSTEM_ERROR", "CANCELED", "PREEMPTED"}
IMAGE = "elixircloud/nvflare-wes-testbed:dev"
# The first site's share of the synthetic test set; see docs/setup/real-sites.md
INPUT_URL = (
    "https://raw.githubusercontent.com/elixir-cloud-aai/nvflare-wes-testbed/"
    "b473b4b2d3246d6b5f74c31e209268e0c093e062/testset/data/site-1.csv"
)
INPUT_SHA256 = "c578295a4bd973bb98fa2def75cffd50313dd9c7ab6b34f6548124a70103c001"
INPUT_PATH = "/probe/input.csv"


def port_list(value: str) -> list[int]:
    """Parse a list of ports.

    Args:
        value: Ports, separated by commas.

    Returns:
        The ports.

    Raises:
        argparse.ArgumentTypeError: Something in the list isn't a port.
    """
    try:
        ports = [int(port) for port in value.split(",") if port.strip()]
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"not a list of ports: {value}") from error
    if not all(0 < port < 65536 for port in ports):
        raise argparse.ArgumentTypeError(f"not a list of ports: {value}")
    return ports


def parse_arguments() -> argparse.Namespace:
    """Parse the command line.

    Returns:
        The arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tes", required=True, help="Base URL of the TES or proTES, without /ga4gh/tes/v1")
    parser.add_argument("--backend", help="Through proTES: base URL of the TES to pin the task to")
    parser.add_argument("--hub", required=True, help="Name or address of the hub")
    parser.add_argument("--fl-port", type=int, default=8002, help="FL port of the hub, which a client must reach")
    parser.add_argument("--ports", type=port_list, default=[443], help="Other ports to try, for information")
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
    targets = [f"{args.hub}:{port}" for port in [args.fl_port, *args.ports]]
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
                    try:
                        return json.loads(line.removeprefix(RESULT_PREFIX))
                    except json.JSONDecodeError:
                        return None
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
    pinned = bool(args.backend) and same_url(backend, args.backend)
    try:
        reply = requests.get(
            f"{backend.rstrip('/')}/ga4gh/tes/v1/tasks/{backend_id}",
            params={"view": "FULL"},
            headers=headers if pinned else {},
            timeout=30,
        )
    except requests.RequestException:
        return None
    return find_result(reply.json()) if reply.ok else None


def same_url(first: str, second: str) -> bool:
    """Compare two base URLs, whether or not they end with a slash.

    Args:
        first: One URL.
        second: The other URL.

    Returns:
        Whether they're the same.
    """
    return first.rstrip("/") == second.rstrip("/")


def verdict(state: str, result: dict[str, Any], fl_target: str) -> tuple[int, str]:
    """Tell whether a node has what a client needs.

    Args:
        state: The final state of the task.
        result: The findings of the probe.
        fl_target: The FL port of the hub, as `<host>:<port>`.

    Returns:
        The exit code, and the line to end with.
    """
    fl_port = result["targets"][fl_target]
    if state != "COMPLETE" or result["input"] != "ok" or not result["env_passed"] or not result["tmp_writable"]:
        return EXIT_CANNOT, "[FAIL] the node can't take part: see above"
    if fl_port == "refused":
        return EXIT_INCONCLUSIVE, f"[inconclusive] {fl_target} refused: is the listener running on the hub?"
    if fl_port != "open":
        return EXIT_CANNOT, f"[FAIL] the node can't take part: {fl_target} is {fl_port}"
    return 0, f"[ok] the node can take part, on {fl_target}"


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
    state = task.get("state", "UNKNOWN")
    print(f"State: {state}")
    backend = (task.get("tags") or {}).get("gateway.backend")
    if backend:
        print(f"Ran at: {backend}")
    if args.backend and not (backend and same_url(backend, args.backend)):
        print(f"[inconclusive] the task should have run at {args.backend}")
        sys.exit(EXIT_INCONCLUSIVE)
    result = find_result(task) or read_from_backend(task, args, headers)
    if result is None:
        print("[inconclusive] no findings in the log of the task: ask the operator of the node for it")
        sys.exit(EXIT_INCONCLUSIVE)
    for target, outcome in result["targets"].items():
        print(f"Port {target}: {outcome}")
    for key in ("input", "env_passed", "uid", "gid", "tmp_writable", "root_writable"):
        print(f"{key}: {result[key]}")
    code, line = verdict(state, result, f"{args.hub}:{args.fl_port}")
    print(line)
    sys.exit(code)


if __name__ == "__main__":
    main()

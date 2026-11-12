"""Check that a run fails at once, and says why, when something else holds the FL port.

The FL server only logs that it can't bind its port, and starts anyway: sites
then dial out to whatever holds the port, never join, and the run ends with a
timeout that names no cause. Seen on Rahti, with the node probe's listener
(`tests/probe.py listen`) left running in the hub's pod.
"""

import os
import pathlib
import socket
import sys
import tempfile
import time


def main() -> None:
    """Hold a port, and check the port check and a run against it."""
    with tempfile.TemporaryDirectory() as directory:
        os.environ["WES_WORKDIR"] = directory
        # A TES that refuses connections: a run that gets as far as its tasks fails otherwise
        os.environ["WES_SITES"] = '{"site-1": {"tes": "http://127.0.0.1:9", "data": "https://example.org/1.csv"}}'
        sys.path.insert(0, "/app")
        from wes import app as wes

        with socket.create_server(("", 0)) as holder:
            port = holder.getsockname()[1]
            wes.FL_PORT = port
            try:
                wes.ensure_port_free(port)
                busy_error = ""
            except RuntimeError as error:
                busy_error = str(error)

            wes.RUNS["r"] = {"state": "QUEUED", "tasks": [], "outputs": {}}
            started = time.monotonic()
            wes.execute("r", pathlib.Path(directory) / "job", ["site-1"])
            took = time.monotonic() - started
            run = wes.RUNS["r"]

        try:
            wes.ensure_port_free(port)
            free_error = ""
        except RuntimeError as error:
            free_error = str(error)

    checks = {
        "a held port is refused": busy_error != "",
        "the refusal names the port": str(port) in busy_error,
        "a free port passes": free_error == "",
        "the run ends with SYSTEM_ERROR": run["state"] == "SYSTEM_ERROR",
        "the run's error says the FL port is in use": "in use" in run.get("error", ""),
        "the run submits no tasks": run["tasks"] == [],
        "the run fails at once, not after the start timeout": took < 30,
    }
    for name, passed in checks.items():
        print(f"[{'ok' if passed else 'FAIL'}] {name}")
    sys.exit(0 if all(checks.values()) else 1)


if __name__ == "__main__":
    main()

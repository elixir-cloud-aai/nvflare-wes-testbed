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
    """Hold a port, and check the port checks and a run against it."""
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

            # A regression that starts an FL server anyway must fail fast, not wait out the start timeout
            wes.START_TIMEOUT = 5
            wes.FL_SERVER_MODE = "local"
            wes.RUNS["r"] = {"state": "QUEUED", "tasks": [], "outputs": {}}
            started = time.monotonic()
            wes.execute("r", pathlib.Path(directory) / "job", ["site-1"])
            took = time.monotonic() - started
            run = wes.RUNS["r"]
            # The FL server of a TES task doesn't run here, so the port of this container doesn't matter
            wes.FL_SERVER_MODE = "tes"
            wes.RUNS["t"] = {"state": "QUEUED", "tasks": [], "outputs": {}}
            wes.execute("t", pathlib.Path(directory) / "job", ["site-1"])
            tes_run = wes.RUNS["t"]
            wes.FL_SERVER_MODE = "local"

        try:
            wes.ensure_port_free(port)
            free_error = ""
        except RuntimeError as error:
            free_error = str(error)

        # What NVFlare's gRPC logs when it can't bind, as on Rahti; the server starts anyway
        log = pathlib.Path(directory) / "server.log"
        log.write_text(
            f"E1112 17:31:44.926438      59 add_port.cc:83] {wes.BIND_FAILURE} to server: No address added out of"
            f" total 1 resolved for '0.0.0.0:{port}' (... Address already in use)\n"
            "2026-11-12 17:31:44,932 - Server - INFO - added secure port at 0.0.0.0:8003\n"
        )
        try:
            wes.check_server_bound(log, port)
            log_error = ""
        except RuntimeError as error:
            log_error = str(error)
        log.write_text("2026-11-12 17:31:44,932 - Server - INFO - added secure port at 0.0.0.0:8003\n")
        try:
            wes.check_server_bound(log, port)
            clean_error = ""
        except RuntimeError as error:
            clean_error = str(error)

    checks = {
        "a held port is refused": busy_error != "",
        "the refusal names the port": str(port) in busy_error,
        "a free port passes": free_error == "",
        "the run ends with SYSTEM_ERROR": run["state"] == "SYSTEM_ERROR",
        "the run's error says the FL port is in use": f"FL port {port} is in use" in run.get("error", ""),
        "the run submits no tasks": run["tasks"] == [],
        "the run fails at once, not after the start timeout": took < 30,
        "a run with the FL server in a TES task skips the check": "is in use" not in tes_run.get("error", ""),
        "a server log with a failed bind is refused": f"FL port {port} is in use" in log_error,
        "a server log without one passes": clean_error == "",
    }
    for name, passed in checks.items():
        print(f"[{'ok' if passed else 'FAIL'}] {name}")
    sys.exit(0 if all(checks.values()) else 1)


if __name__ == "__main__":
    main()

"""Check that a run fails at once, and says why, when something else holds the FL port.

The FL server only logs that it can't bind its port, and starts anyway: sites
then dial out to whatever holds the port, never join, and the run ends with a
timeout that names no cause. Seen on Rahti, with the node probe's listener
(`tests/probe.py listen`) left running in the hub's pod.

A standalone script, run once per process: it changes globals of the WES.
"""

import errno
import os
import pathlib
import socket
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from typing import Any
from unittest import mock

# What gRPC logged on Rahti when it couldn't bind the FL port, literally, so a
# wrong marker in the WES fails here; and NVFlare's line for a port it did bind
FAILED_BIND = (
    "E1112 17:31:44.926438      59 add_port.cc:83] Failed to add port to server: No address added out of"
    " total 1 resolved for '0.0.0.0:{port}' (Failed to add any wildcard listeners: Error in bind for address"
    " '0.0.0.0:{port}': Address already in use)\n"
)
BOUND = "2026-11-12 17:31:44,932 - Server - INFO - added secure port at 0.0.0.0:{port}\n"


def error_of(call: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
    """Call something, and get the message of the RuntimeError it raises.

    Args:
        call: What to call.
        *args: Its positional arguments.
        **kwargs: Its keyword arguments.

    Returns:
        The message, or an empty string if it raised none.
    """
    try:
        call(*args, **kwargs)
    except RuntimeError as error:
        return str(error)
    return ""


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
            busy_error = error_of(wes.ensure_port_free, port)

            # A regression that starts an FL server anyway must fail fast, not wait out the start timeout
            wes.START_TIMEOUT = 5
            wes.FL_SERVER_MODE = "local"
            wes.RUNS["r"] = {"state": "QUEUED", "tasks": [], "outputs": {}}
            started = time.monotonic()
            wes.execute("r", pathlib.Path(directory) / "job", ["site-1"], "probe@testbed.invalid")
            took = time.monotonic() - started
            run = wes.RUNS["r"]
            # The FL server of a TES task doesn't run here, so the port of this container doesn't matter
            wes.FL_SERVER_MODE = "tes"
            wes.RUNS["t"] = {"state": "QUEUED", "tasks": [], "outputs": {}}
            wes.execute("t", pathlib.Path(directory) / "job", ["site-1"], "probe@testbed.invalid")
            tes_run = wes.RUNS["t"]
            wes.FL_SERVER_MODE = "local"

        free_error = error_of(wes.ensure_port_free, port)
        # Other reasons not to bind are not a held port
        with mock.patch.object(wes.socket, "create_server", side_effect=PermissionError(errno.EACCES, "denied")):
            denied_error = error_of(wes.ensure_port_free, port)

        log = pathlib.Path(directory) / "server.log"
        log.write_text(FAILED_BIND.format(port=port) + BOUND.format(port=8003))
        log_error = error_of(wes.check_server_bound, log, port, timeout=5)
        log.write_text(BOUND.format(port=8003) + BOUND.format(port=port))
        started = time.monotonic()
        clean_error = error_of(wes.check_server_bound, log, port, timeout=5)
        clean_took = time.monotonic() - started
        # The FL port's line comes after the admin port's, and the check waits for it
        log.write_text(BOUND.format(port=8003))
        late = threading.Timer(0.5, lambda: log.write_text(FAILED_BIND.format(port=port)))
        late.start()
        late_error = error_of(wes.check_server_bound, log, port, timeout=5)
        late.join()
        # A log with neither line, as with other wording, lets the run go on after the timeout
        log.write_text(BOUND.format(port=8003))
        silent_error = error_of(wes.check_server_bound, log, port, timeout=0.5)

    checks = {
        "a held port is refused": busy_error != "",
        "the refusal names the port": f"FL port {port} is in use" in busy_error,
        "a free port passes": free_error == "",
        "a port that can't be bound for another reason isn't called in use": "in use" not in denied_error
        and str(port) in denied_error,
        "the run ends with SYSTEM_ERROR": run["state"] == "SYSTEM_ERROR",
        "the run's error says the FL port is in use": f"FL port {port} is in use" in run.get("error", ""),
        "the run submits no tasks": run["tasks"] == [],
        "the run fails at once, not after the start timeout": took < 30,
        "a run with the FL server in a TES task skips the check": "is in use" not in tes_run.get("error", ""),
        "a server log with a failed bind is refused": f"FL port {port} is in use" in log_error,
        "a server log with the FL port bound passes at once": clean_error == "" and clean_took < 2,
        "a failed bind logged late is refused": f"FL port {port} is in use" in late_error,
        "a server log with neither line passes after the timeout": silent_error == "",
    }
    for name, passed in checks.items():
        print(f"[{'ok' if passed else 'FAIL'}] {name}")
    sys.exit(0 if all(checks.values()) else 1)


if __name__ == "__main__":
    main()

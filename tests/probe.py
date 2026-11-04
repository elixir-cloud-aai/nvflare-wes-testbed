"""Check what can be reached from where this runs: test T3, and the node probe.

Usage:
    probe.py open=<host>:<port> closed=<host>:<port> ...
    probe.py node <input-path> <input-sha256> <host>:<port> ...

The second form is what the probe task runs at a TES node (see `probe_submit.py`).
It prints one line with what the node allows, and always ends with 0, as anything
it finds is a result, not a failure of the task.
"""

import hashlib
import json
import os
import pathlib
import socket
import sys
import tempfile

RESULT_PREFIX = "PROBE-RESULT "


def connect(host: str, port: int) -> str:
    """Try to connect, and tell what happened.

    Args:
        host: The host.
        port: The port.

    Returns:
        `open`, or else why not: `refused` (the host answered, so the way there
        is free, but nothing listens), `timeout` (likely a firewall), `no-name`
        or `unreachable`.
    """
    try:
        with socket.create_connection((host, port), timeout=5):
            return "open"
    except socket.gaierror:
        return "no-name"
    except ConnectionRefusedError:
        return "refused"
    except TimeoutError:
        return "timeout"
    except OSError:
        return "unreachable"


def split_target(target: str) -> tuple[str, int]:
    """Split a target into host and port.

    Args:
        target: The target, as `<host>:<port>`.

    Returns:
        The host and the port.
    """
    host, _, port = target.rpartition(":")
    return host, int(port)


def is_writable(directory: str) -> bool:
    """Tell whether files can be created in a directory.

    Args:
        directory: The directory.

    Returns:
        Whether a file could be created there.
    """
    try:
        with tempfile.TemporaryFile(dir=directory):
            return True
    except OSError:
        return False


def input_state(path: pathlib.Path, sha256: str) -> str:
    """Check an input of the task.

    Args:
        path: Where the input should be.
        sha256: Its expected checksum.

    Returns:
        `ok`, `different` or `missing`.
    """
    if not path.is_file():
        return "missing"
    return "ok" if hashlib.sha256(path.read_bytes()).hexdigest() == sha256 else "different"


def node_report(input_path: str, sha256: str, targets: list[str]) -> dict[str, object]:
    """Find out what a node allows a task to do.

    Args:
        input_path: Where the `https` input of the task should be.
        sha256: The expected checksum of the input.
        targets: Where to connect to, as `<host>:<port>`.

    Returns:
        The findings.
    """
    return {
        "targets": {target: connect(*split_target(target)) for target in targets},
        "input": input_state(pathlib.Path(input_path), sha256),
        "env_passed": os.environ.get("PROBE_ENV") == "passed",
        "uid": os.getuid(),
        "gid": os.getgid(),
        "tmp_writable": is_writable("/tmp"),
        "root_writable": is_writable("/"),
    }


def check_expected(arguments: list[str]) -> int:
    """Check targets against expected outcomes.

    Args:
        arguments: The targets, as `open=<host>:<port>` or `closed=<host>:<port>`.

    Returns:
        The number of unexpected outcomes.
    """
    failed = 0
    for argument in arguments:
        expected, _, target = argument.partition("=")
        outcome = "open" if connect(*split_target(target)) == "open" else "closed"
        print(f"[{'ok' if outcome == expected else 'FAIL'}] {target}: {outcome}, expected {expected}")
        failed += outcome != expected
    return failed


def main() -> None:
    """Run the form of the probe that the arguments ask for."""
    if sys.argv[1:2] == ["node"]:
        print(RESULT_PREFIX + json.dumps(node_report(sys.argv[2], sys.argv[3], sys.argv[4:])), flush=True)
        return
    sys.exit(1 if check_expected(sys.argv[1:]) else 0)


if __name__ == "__main__":
    main()

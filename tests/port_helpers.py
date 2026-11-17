"""Helpers for the tests of the probe responder: free ports, binding, and waiting for an answer."""

import socket
import time

from probe import connect


def free_port() -> int:
    """Find a port that nothing listens on.

    Returns:
        The port.
    """
    with socket.create_server(("", 0)) as server:
        return server.getsockname()[1]


def can_bind(port: int) -> bool:
    """Tell whether a port is free to listen on, as the FL server needs it.

    Args:
        port: The port.

    Returns:
        Whether it could be bound.
    """
    try:
        with socket.create_server(("", port)):
            return True
    except OSError:
        return False


def wait_until_open(port: int, timeout: float = 5) -> str:
    """Wait until a port of this host answers.

    Args:
        port: The port.
        timeout: Seconds to wait.

    Returns:
        What the probe saw last: `open`, or why not.
    """
    deadline = time.monotonic() + timeout
    outcome = connect("127.0.0.1", port)
    while outcome != "open" and time.monotonic() < deadline:
        time.sleep(0.05)
        outcome = connect("127.0.0.1", port)
    return outcome

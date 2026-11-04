"""Check what can be reached from the network this runs on: test T3 of the docs.

Usage: probe.py open=<host>:<port> closed=<host>:<port> ...
"""

import socket
import sys


def reachable(host: str, port: int) -> bool:
    """Try to connect.

    Args:
        host: The host.
        port: The port.

    Returns:
        Whether the connection succeeded.
    """
    try:
        with socket.create_connection((host, port), timeout=5):
            return True
    except OSError:
        return False


def main() -> None:
    """Check all arguments, and fail if any has an unexpected outcome."""
    failed = 0
    for argument in sys.argv[1:]:
        expected, _, target = argument.partition("=")
        host, _, port = target.rpartition(":")
        outcome = "open" if reachable(host, int(port)) else "closed"
        print(f"[{'ok' if outcome == expected else 'FAIL'}] {target}: {outcome}, expected {expected}")
        failed += outcome != expected
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

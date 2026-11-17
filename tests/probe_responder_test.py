"""Unit tests of `wes/probe_responder.py`, on ports of this host. No other network needed.

Usage: python3 tests/probe_responder_test.py
"""

import pathlib
import socket
import sys
import time
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from probe import connect

from wes.probe_responder import ProbeResponder, responder_enabled


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


class ProbeResponderTest(unittest.TestCase):
    """The responder's lifecycle: answer, stop, start again, wait for a held port."""

    def setUp(self) -> None:
        """Make a responder on a free port, stopped at the end of each test."""
        self.port = free_port()
        self.responder = ProbeResponder(self.port, retry=0.1, poll=0.05)
        self.addCleanup(self.responder.stop)

    def test_answers_while_started(self) -> None:
        """A probe gets `open`, as from `tests/probe.py listen`, and may connect again."""
        self.responder.start()
        self.assertEqual(wait_until_open(self.port), "open")
        self.assertTrue(self.responder.listening)
        self.assertEqual(connect("127.0.0.1", self.port), "open")

    def test_not_listening_before_start(self) -> None:
        """Nothing listens before the responder starts."""
        self.assertFalse(self.responder.listening)
        self.assertEqual(connect("127.0.0.1", self.port), "refused")

    def test_stop_frees_the_port(self) -> None:
        """Once `stop` returns, the port is free for the FL server, at once."""
        self.responder.start()
        self.assertEqual(wait_until_open(self.port), "open")
        self.assertTrue(self.responder.stop())
        self.assertFalse(self.responder.listening)
        self.assertTrue(can_bind(self.port))
        self.assertEqual(connect("127.0.0.1", self.port), "refused")

    def test_starts_again_after_stop(self) -> None:
        """A run after a run: the responder answers again after each one."""
        for _ in range(3):
            self.responder.start()
            self.assertEqual(wait_until_open(self.port), "open")
            self.assertTrue(self.responder.stop())
            self.assertTrue(can_bind(self.port))

    def test_start_twice_keeps_one_listener(self) -> None:
        """A second `start` is a no-op, not a second socket that fails to bind."""
        self.responder.start()
        self.responder.start()
        self.assertEqual(wait_until_open(self.port), "open")
        self.assertTrue(self.responder.stop())
        self.assertTrue(can_bind(self.port))

    def test_stop_without_start(self) -> None:
        """`stop` on a responder that never started does nothing, and says so."""
        self.assertTrue(self.responder.stop())
        self.assertTrue(can_bind(self.port))

    def test_waits_for_a_held_port(self) -> None:
        """While something else holds the port, it waits, and answers once it's free."""
        with socket.create_server(("", self.port)) as holder:
            self.responder.start()
            time.sleep(0.3)
            self.assertFalse(self.responder.listening)
            # The holder accepts nothing, but its backlog makes the port look open
            holder.close()
        self.assertEqual(wait_until_open(self.port), "open")
        self.assertTrue(self.responder.listening)

    def test_stop_while_waiting_for_a_held_port(self) -> None:
        """A responder that waits for a held port stops at once, and leaves the holder alone."""
        responder = ProbeResponder(self.port, retry=30, poll=0.05)
        with socket.create_server(("", self.port)):
            responder.start()
            time.sleep(0.1)
            started = time.monotonic()
            self.assertTrue(responder.stop())
            self.assertLess(time.monotonic() - started, 5)
            self.assertEqual(connect("127.0.0.1", self.port), "open")


class ResponderEnabledTest(unittest.TestCase):
    """The setting that switches the responder off (`FL_PROBE_RESPONDER`)."""

    def test_on_by_default(self) -> None:
        """Unset means on."""
        self.assertTrue(responder_enabled(None))

    def test_on(self) -> None:
        """Usual words for on, in any case and with spaces around them."""
        for value in ("1", "true", "True", "yes", "on", " ON "):
            with self.subTest(value=value):
                self.assertTrue(responder_enabled(value))

    def test_off(self) -> None:
        """Usual words for off, and an empty value, as `FL_PROBE_RESPONDER=` reads as off."""
        for value in ("0", "false", "FALSE", "no", "off", "", " "):
            with self.subTest(value=value):
                self.assertFalse(responder_enabled(value))

    def test_other_values_are_refused(self) -> None:
        """A typo fails the start of the hub, rather than pick a side, and names the variable."""
        with self.assertRaisesRegex(ValueError, "FL_PROBE_RESPONDER"):
            responder_enabled("maybe")


if __name__ == "__main__":
    unittest.main()

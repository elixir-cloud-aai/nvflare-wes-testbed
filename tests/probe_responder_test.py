"""Unit tests of `wes/probe_responder.py`, on ports of this host. No other network needed.

Usage: python3 tests/probe_responder_test.py
"""

import pathlib
import socket
import sys
import threading
import time
import unittest
from typing import Any
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from port_helpers import can_bind, free_port, wait_until_open
from probe import connect

from wes.probe_responder import ProbeResponder, responder_enabled


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
        holder = socket.create_server(("", self.port))
        self.responder.start()
        time.sleep(0.3)
        # The port is held, so the responder doesn't listen yet
        self.assertFalse(self.responder.listening)
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

    def test_stop_that_times_out(self) -> None:
        """A thread that doesn't end in time: `stop` says so, no second thread starts beside it, and a start
        asked for meanwhile follows once it has ended.
        """
        release = threading.Event()
        bind = socket.create_server

        def stuck(*args: Any, **kwargs: Any) -> socket.socket:
            """Bind once released, as a thread stuck in a system call would.

            Args:
                *args: Those of `socket.create_server`.
                **kwargs: Those of `socket.create_server`.

            Returns:
                The socket.
            """
            release.wait(5)
            return bind(*args, **kwargs)

        with mock.patch("wes.probe_responder.socket.create_server", side_effect=stuck):
            self.responder.start()
            time.sleep(0.1)
            self.assertFalse(self.responder.stop(timeout=0.1))
            with mock.patch("threading.Thread.start") as start:
                self.responder.start()
            start.assert_not_called()
            # Once the old thread has ended, the start asked for meanwhile takes effect on its own
            release.set()
            self.assertEqual(wait_until_open(self.port), "open")
        self.assertTrue(self.responder.stop())
        self.assertTrue(can_bind(self.port))


class ResponderEnabledTest(unittest.TestCase):
    """The setting that switches the responder off (`FL_PROBE_RESPONDER`)."""

    def test_on_by_default(self) -> None:
        """Unset or empty means on, as Compose's `${FL_PROBE_RESPONDER:-1}` reads it."""
        for value in (None, "", " "):
            with self.subTest(value=value):
                self.assertTrue(responder_enabled(value))

    def test_on(self) -> None:
        """Usual words for on, in any case and with spaces around them."""
        for value in ("1", "true", "True", "yes", "on", " ON "):
            with self.subTest(value=value):
                self.assertTrue(responder_enabled(value))

    def test_off(self) -> None:
        """Usual words for off, in any case."""
        for value in ("0", "false", "FALSE", "no", "off"):
            with self.subTest(value=value):
                self.assertFalse(responder_enabled(value))

    def test_other_values_are_refused(self) -> None:
        """A typo fails the start of the hub, rather than pick a side, and names the variable."""
        with self.assertRaisesRegex(ValueError, "FL_PROBE_RESPONDER"):
            responder_enabled("maybe")


if __name__ == "__main__":
    unittest.main()

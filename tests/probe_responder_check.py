"""Check how the WES runs its probe responder around runs (`wes/probe_responder.py`).

The responder answers probes on the FL port while no run is active, and must
never be in the way of a run: the WES stops it before the FL server starts, and
starts it again when the run has ended. Runs stop early here, at a stub of the
first step after the port check, so no FL server starts, and no network is needed.

A standalone script, run once per process, in the image (`tests/hub.sh`): it
changes globals of the WES.

Usage: python3 tests/probe_responder_check.py
"""

import os
import pathlib
import socket
import sys
import tempfile
import time
import unittest
from typing import Any
from unittest import mock

import anyio

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from probe import connect

WORKDIR = tempfile.TemporaryDirectory()
os.environ["WES_WORKDIR"] = WORKDIR.name
# A TES that refuses connections, should a run get as far as its tasks
os.environ["WES_SITES"] = '{"site-1": {"tes": "http://127.0.0.1:9", "data": "https://example.org/1.csv"}}'

from wes import app as wes
from wes.probe_responder import ProbeResponder

STUB_ERROR = "stopped here by the check"


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


class ProbeResponderCheck(unittest.TestCase):
    """The responder in the WES: at startup, around runs, and when switched off."""

    def setUp(self) -> None:
        """Give the WES a responder on a free port, as its FL port, with NVFlare stubbed after the port check."""
        self.port = free_port()
        self.responder = ProbeResponder(self.port, retry=0.1, poll=0.05)
        self.addCleanup(self.responder.stop)
        self.seen: list[dict[str, bool]] = []
        patches = [
            mock.patch.object(wes, "FL_PORT", self.port),
            mock.patch.object(wes, "FL_SERVER_MODE", "local"),
            mock.patch.object(wes, "RESPONDER", self.responder),
            mock.patch.object(wes, "init_ca", side_effect=self.at_first_step),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        # `execute` imports the FLARE API first, which only the image has; no run gets as far as using it
        modules = {name: mock.MagicMock() for name in ("nvflare", "nvflare.fuel", "nvflare.fuel.flare_api")}
        modules["nvflare.fuel.flare_api.flare_api"] = mock.MagicMock()
        stub = mock.patch.dict(sys.modules, modules)
        stub.start()
        self.addCleanup(stub.stop)

    def at_first_step(self, *args: Any) -> str:
        """Stand in for `init_ca`: see what the run would find, then end it.

        Args:
            *args: Those of `init_ca`.

        Raises:
            RuntimeError: Always, to end the run before an FL server starts.
        """
        self.seen.append({"listening": self.responder.listening, "port_free": can_bind(self.port)})
        raise RuntimeError(STUB_ERROR)

    def run_once(self) -> dict[str, Any]:
        """Carry out a run, which ends at the stub.

        Returns:
            The run.
        """
        run_id = f"run-{len(wes.RUNS)}"
        wes.RUNS[run_id] = {"state": "QUEUED", "tasks": [], "outputs": {}}
        wes.execute(run_id, pathlib.Path(WORKDIR.name) / "job", ["site-1"], "probe@testbed.invalid")
        return wes.RUNS[run_id]

    def test_make_responder(self) -> None:
        """On by default, off when switched off, and off with the FL server in a TES task."""
        self.assertIsInstance(wes.make_responder(None, "local", 8002), ProbeResponder)
        self.assertEqual(wes.make_responder(None, "local", 8002).port, 8002)
        self.assertIsNone(wes.make_responder("0", "local", 8002))
        self.assertIsNone(wes.make_responder("false", "local", 8002))
        # There, the FL port of this container isn't the one that sites dial
        self.assertIsNone(wes.make_responder(None, "tes", 8002))
        with self.assertRaisesRegex(ValueError, "FL_PROBE_RESPONDER"):
            wes.make_responder("maybe", "local", 8002)

    def test_lifespan_starts_and_stops_it(self) -> None:
        """The WES answers probes once it has started, and frees the port when it shuts down."""
        outcomes: list[str] = []

        async def serve() -> None:
            async with wes.lifespan(wes.app):
                outcomes.append(await anyio.to_thread.run_sync(wait_until_open, self.port))

        anyio.run(serve)
        self.assertEqual(outcomes, ["open"])
        self.assertTrue(can_bind(self.port))

    def test_run_starts_while_it_answers(self) -> None:
        """A run stops the responder before its port check, finds the port free, and starts it again."""
        self.responder.start()
        self.assertEqual(wait_until_open(self.port), "open")
        run = self.run_once()
        self.assertEqual(self.seen, [{"listening": False, "port_free": True}])
        self.assertIn(STUB_ERROR, run.get("error", ""))
        self.assertNotIn("is in use", run.get("error", ""))
        self.assertEqual(wait_until_open(self.port), "open")

    def test_run_after_run(self) -> None:
        """Each run finds the port free, and the responder answers again after each one."""
        self.responder.start()
        for _ in range(3):
            self.assertEqual(wait_until_open(self.port), "open")
            run = self.run_once()
            self.assertIn(STUB_ERROR, run.get("error", ""))
        self.assertEqual(self.seen, [{"listening": False, "port_free": True}] * 3)
        self.assertEqual(wait_until_open(self.port), "open")

    def test_answers_after_a_run_also_if_it_was_down(self) -> None:
        """After a run, the responder answers, even if it didn't run before (such as after a failed bind)."""
        self.run_once()
        self.assertEqual(wait_until_open(self.port), "open")

    def test_foreign_listener_still_fails_the_run(self) -> None:
        """A probe listener left behind still fails a run at once (#41); the responder leaves it alone."""
        with socket.create_server(("", self.port)):
            self.responder.start()
            run = self.run_once()
            self.assertEqual(self.seen, [])
            self.assertEqual(run["state"], "SYSTEM_ERROR")
            self.assertIn(f"FL port {self.port} is in use", run.get("error", ""))
            self.assertFalse(self.responder.listening)
        # Once it's gone, the responder takes over
        self.assertEqual(wait_until_open(self.port), "open")

    def test_switched_off(self) -> None:
        """Without a responder, nothing answers before or after a run, and runs go on as before."""
        with mock.patch.object(wes, "RESPONDER", None):
            self.assertEqual(connect("127.0.0.1", self.port), "refused")
            run = self.run_once()
            self.assertEqual(self.seen, [{"listening": False, "port_free": True}])
            self.assertIn(STUB_ERROR, run.get("error", ""))
            time.sleep(0.3)
            self.assertEqual(connect("127.0.0.1", self.port), "refused")


if __name__ == "__main__":
    unittest.main()

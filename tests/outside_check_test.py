"""Unit tests of `outside_check.py`, with local servers and mocked requests. No network needed.

Usage: python3 tests/outside_check_test.py
"""

import http.server
import json
import socket
import threading
import unittest
from unittest import mock

import outside_check
from outside_check import Answer, Result


class Handler(http.server.BaseHTTPRequestHandler):
    """Answers as the WES does: 404 with a detail for kits and tokens, 200 else."""

    def do_GET(self) -> None:
        """Answer a GET."""
        if self.path.startswith("/kits/"):
            self.reply(404, json.dumps({"detail": "No such kit"}))
        else:
            self.reply(200, "plain text")

    def do_POST(self) -> None:
        """Answer a POST."""
        self.reply(404, json.dumps({"detail": "No such token"}))

    def reply(self, status: int, body: str) -> None:
        """Send a status and a body.

        Args:
            status: HTTP status.
            body: Body.
        """
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args: object) -> None:
        """Keep the test's output clean.

        Args:
            *args: Ignored.
        """


def free_port() -> int:
    """Find a port that nothing listens on.

    Returns:
        The port.
    """
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class RequestTest(unittest.TestCase):
    """`request` and `tcp_open`, against a local server."""

    @classmethod
    def setUpClass(cls) -> None:
        """Start a local HTTP server."""
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        """Stop the server."""
        cls.server.shutdown()
        cls.server.server_close()

    def test_success(self) -> None:
        """A 200 comes back with its body."""
        self.assertEqual(outside_check.request(f"{self.base}/other"), Answer(200, "plain text"))

    def test_error_status(self) -> None:
        """An error status comes back with its body, and its detail can be read."""
        answer = outside_check.request(f"{self.base}/kits/x/y")
        self.assertEqual(answer.status, 404)
        self.assertEqual(outside_check.detail(answer), "No such kit")

    def test_post(self) -> None:
        """A POST is sent as a POST."""
        answer = outside_check.request(f"{self.base}/sites/x/csr", method="POST")
        self.assertEqual(outside_check.detail(answer), "No such token")

    def test_no_answer(self) -> None:
        """A closed port gives no status, and a reason."""
        answer = outside_check.request(f"http://127.0.0.1:{free_port()}/", timeout=2)
        self.assertIsNone(answer.status)
        self.assertTrue(answer.error)

    def test_tcp_open(self) -> None:
        """A listening port is open, and a free one is closed, with a reason."""
        self.assertEqual(outside_check.tcp_open("127.0.0.1", self.server.server_port), (True, ""))
        is_open, error = outside_check.tcp_open("127.0.0.1", free_port(), timeout=2)
        self.assertFalse(is_open)
        self.assertTrue(error)


class DescribeTest(unittest.TestCase):
    """`detail` and `describe`."""

    def test_detail(self) -> None:
        """Only a JSON object's detail counts."""
        self.assertEqual(outside_check.detail(Answer(404, '{"detail": "No such kit"}')), "No such kit")
        self.assertIsNone(outside_check.detail(Answer(404, "<html>Not found</html>")))
        self.assertIsNone(outside_check.detail(Answer(404, '["detail"]')))
        self.assertIsNone(outside_check.detail(Answer(404, "{}")))

    def test_describe(self) -> None:
        """Status and detail, or why nothing answered."""
        self.assertEqual(outside_check.describe(Answer(404, '{"detail": "No such kit"}')), "404 'No such kit'")
        self.assertEqual(outside_check.describe(Answer(403)), "403")
        self.assertEqual(outside_check.describe(Answer(None, error="timed out")), "no answer (timed out)")


class ChecksTest(unittest.TestCase):
    """Each check's verdict on what came back."""

    def check_open_path(self, answer: Answer) -> Result:
        """Run the check of `/kits` on a mocked answer.

        Args:
            answer: What the request gets.

        Returns:
            The result.
        """
        with mock.patch.object(outside_check, "request", return_value=answer) as request:
            result = outside_check.check_open_path(
                "kits.example.org", "/kits/t/site-1.tgz", "GET", "No such kit", verify=True, timeout=1
            )
        request.assert_called_once_with(
            "https://kits.example.org/kits/t/site-1.tgz", method="GET", verify=True, timeout=1
        )
        return result

    def test_open_path(self) -> None:
        """Only the WES' own 404 shows that the way is open."""
        self.assertEqual(self.check_open_path(Answer(404, '{"detail": "No such kit"}')).outcome, "ok")
        # A 404 of a router or proxy, not of the WES
        self.assertEqual(self.check_open_path(Answer(404, "<html>Not found</html>")).outcome, "FAIL")
        self.assertEqual(self.check_open_path(Answer(403)).outcome, "FAIL")
        self.assertEqual(self.check_open_path(Answer(503, "Application not available")).outcome, "FAIL")
        self.assertEqual(self.check_open_path(Answer(None, error="timed out")).outcome, "FAIL")

    def test_no_wes(self) -> None:
        """Anything but 200 is fine, also no answer at all, and certificates aren't checked."""
        for answer, outcome in [
            (Answer(200, "{}"), "FAIL"),
            (Answer(403), "ok"),
            (Answer(503), "ok"),
            (Answer(None, error="refused"), "ok"),
        ]:
            with mock.patch.object(outside_check, "request", return_value=answer) as request:
                self.assertEqual(outside_check.check_no_wes("hub.example.org", timeout=1).outcome, outcome)
            request.assert_called_once_with(
                "https://hub.example.org/ga4gh/wes/v1/service-info", verify=False, timeout=1
            )

    def test_fl_port(self) -> None:
        """A closed FL port only fails during a run."""
        for is_open, during_run, outcome in [
            (True, False, "ok"),
            (True, True, "ok"),
            (False, False, "warn"),
            (False, True, "FAIL"),
        ]:
            with mock.patch.object(outside_check, "tcp_open", return_value=(is_open, "" if is_open else "refused")):
                result = outside_check.check_fl_port("hub.example.org", 30002, during_run=during_run, timeout=1)
            self.assertEqual(result.outcome, outcome, (is_open, during_run))

    def test_admin_closed(self) -> None:
        """An open admin port fails."""
        with mock.patch.object(outside_check, "tcp_open", return_value=(True, "")):
            self.assertEqual(outside_check.check_admin_closed("hub.example.org", 8003, timeout=1).outcome, "FAIL")
        with mock.patch.object(outside_check, "tcp_open", return_value=(False, "timed out")):
            self.assertEqual(outside_check.check_admin_closed("hub.example.org", 8003, timeout=1).outcome, "ok")


class MainTest(unittest.TestCase):
    """What runs, what's printed, and the exit code."""

    def run_main(self, argv: list[str], answers: dict[str, Answer], ports: dict[int, bool]) -> tuple[int, list[str]]:
        """Run `main` on mocked requests and ports.

        Args:
            argv: Arguments.
            answers: Answer by URL.
            ports: Whether each port is open.

        Returns:
            Exit code, and the printed lines.
        """
        calls = []

        def request(url: str, **kwargs: object) -> Answer:
            calls.append((url, kwargs))
            return answers[url]

        with (
            mock.patch.object(outside_check, "request", side_effect=request),
            mock.patch.object(
                outside_check, "tcp_open", side_effect=lambda host, port, **_: (ports[port], "" if ports[port] else "x")
            ),
            mock.patch("builtins.print") as printed,
        ):
            code = outside_check.main(argv)
        self.calls = calls
        return code, [call.args[0] for call in printed.call_args_list]

    def answers(self, wes: int = 403) -> dict[str, Answer]:
        """Answers of a well set-up hub, at hub.example.org and kits.example.org.

        Args:
            wes: Status of the WES' service info.

        Returns:
            Answer by URL.
        """
        return {
            "https://kits.example.org/kits/no-such-token/site-1.tgz": Answer(404, '{"detail": "No such kit"}'),
            "https://kits.example.org/sites/no-such-token/csr": Answer(404, '{"detail": "No such token"}'),
            "https://kits.example.org/ga4gh/wes/v1/service-info": Answer(wes),
            "https://hub.example.org/ga4gh/wes/v1/service-info": Answer(None, error="refused"),
        }

    def test_all_pass(self) -> None:
        """A good hub passes, with a warning for an FL port closed outside a run."""
        code, lines = self.run_main(
            ["hub.example.org", "kits.example.org", "--fl-port", "30002"], self.answers(), {30002: False, 8003: False}
        )
        self.assertEqual(code, 0)
        self.assertEqual([line.split("]")[0] for line in lines[:-1]], ["[ok"] * 4 + ["[warn", "[ok"])
        self.assertEqual(lines[-1], "all 6 checks passed")
        self.assertIn(
            ("https://kits.example.org/sites/no-such-token/csr", {"method": "POST", "verify": True, "timeout": 10}),
            self.calls,
        )

    def test_failures(self) -> None:
        """A WES that answers and an open admin port fail, and the count says so."""
        code, lines = self.run_main(
            ["hub.example.org", "kits.example.org", "--during-run", "--insecure"],
            self.answers(wes=200),
            {8002: True, 8003: True},
        )
        self.assertEqual(code, 1)
        self.assertEqual(sum(line.startswith("[FAIL]") for line in lines), 2)
        self.assertEqual(lines[-1], "2 of 6 checks failed")
        self.assertFalse(any(kwargs["verify"] for _, kwargs in self.calls))

    def test_same_name(self) -> None:
        """With one name for both, as with Compose, the WES is checked once."""
        answers = {url.replace("kits.example.org", "hub.example.org"): a for url, a in self.answers().items()}
        code, lines = self.run_main(["hub.example.org", "hub.example.org"], answers, {8002: False, 8003: False})
        self.assertEqual(code, 0)
        self.assertEqual(lines[-1], "all 5 checks passed")


if __name__ == "__main__":
    unittest.main()

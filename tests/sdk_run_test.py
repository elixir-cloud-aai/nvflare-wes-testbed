"""Unit tests of `scripts/sdk_run.py`, with a fake `ga4gh-cli` and a fake hub. No other network needed.

Usage: python3 tests/sdk_run_test.py
"""

import base64
import contextlib
import hashlib
import http.server
import io
import json
import os
import pathlib
import sys
import tarfile
import tempfile
import threading
import time
import unittest
from collections.abc import Iterator
from typing import Any, ClassVar
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "scripts"))

import sdk_run

# Decoy: must never show up in the CLI's arguments, its configuration, or the results row
SIGNATURE = "decoy-signature"
WES = "https://flare-wes.example.org/ga4gh/wes/v1"
GATEWAY = "https://gateway.example.org/ga4gh/tes/v1"
TES_1 = "https://tes-1.example.org"
TES_2 = "https://tes-2.example.org"

# Answers as the CLI prints them; `FAKE_CLI_SCENARIO` names a JSON file with
# what to change, and `FAKE_CLI_LOG` a file to note each call in
FAKE_CLI = r"""#!/usr/bin/env python3
import json, os, pathlib, sys
scenario = json.loads(pathlib.Path(os.environ["FAKE_CLI_SCENARIO"]).read_text())
config = (pathlib.Path(os.environ["HOME"]) / ".ga4gh-cli" / "config.json").read_text()
with open(os.environ["FAKE_CLI_LOG"], "a") as log:
    log.write(json.dumps({"argv": sys.argv[1:], "token": os.environ.get("NVFLARE_WES_SDK_TOKEN"),
                          "config": config, "rust_log": os.environ.get("RUST_LOG")}) + "\n")
args = sys.argv[1:]
def fail(status):
    print(f"Error: HTTP status {status}", file=sys.stderr)
    sys.exit(1)
if args == ["--version"]:
    print("ga4gh-cli 0.1.0")
elif args[:1] == ["service-info"]:
    if scenario.get("garbage"):
        print("<html>not JSON</html>")
        sys.exit(0)
    print(json.dumps({"workflow_type_versions": {"NVFLARE": {}}, "tags": {"sites": "site-1,site-2"}}))
elif args[:2] == ["wes", "run"]:
    if scenario.get("echo_token"):
        print("Authorization: Bearer " + os.environ["NVFLARE_WES_SDK_TOKEN"], file=sys.stderr)
        fail(500)
    if scenario.get("submit_status"):
        fail(scenario["submit_status"])
    print(json.dumps({"run_id": "0123456789abcdef"}))
elif args[:2] == ["wes", "status"]:
    count = pathlib.Path(os.environ["FAKE_CLI_LOG"]).read_text().count('"status"')
    if count <= scenario.get("status_failures", 0):
        fail(502)
    count -= scenario.get("status_failures", 0)
    states = scenario.get("states", ["QUEUED", "RUNNING", "COMPLETE"])
    print(states[min(count, len(states)) - 1])
elif args[:2] == ["wes", "get"]:
    if scenario.get("get_status"):
        fail(scenario["get_status"])
    print(json.dumps({
        "run_id": args[2], "state": scenario.get("states", ["COMPLETE"])[-1],
        "run_log": {"system_logs": [], "start_time": "2026-11-29T10:00:00Z", "end_time": "2026-11-29T10:01:32Z"},
        "task_logs": [
            {"id": "task-s", "name": "fl-server", "system_logs": ["COMPLETE"]},
            {"id": "task-2", "name": "fl-client site-2", "system_logs": ["COMPLETE"]},
            {"id": "task-1", "name": "fl-client site-1", "system_logs": ["COMPLETE"]},
        ],
        "outputs": {"flare_job_status": "FINISHED:COMPLETED", "global_model": "/outputs/x/global_model.npy"},
    }))
elif args[:2] == ["tes", "get"]:
    if scenario.get("tes_status"):
        fail(scenario["tes_status"])
    if "pin" in scenario:
        tags = {"gateway.backend": "https://tes-1.example.org"}
        if scenario["pin"] is not None:
            tags["gateway.backends"] = json.dumps(scenario["pin"])
        print(json.dumps({"id": args[2], "state": "COMPLETE", "tags": tags}))
        sys.exit(0)
    pinned = {"task-1": "https://tes-1.example.org", "task-2": "https://tes-2.example.org"}[args[2]]
    ran = scenario.get("ran", {}).get(args[2], pinned)
    print(json.dumps({"id": args[2], "state": "COMPLETE", "tags": {
        "gateway.backends": json.dumps({"type": "allow", "backends": [pinned]}), "gateway.backend": ran}}))
else:
    fail(400)
"""


def make_token(seconds: int) -> str:
    """Make an unsigned JWT that expires in some seconds.

    Args:
        seconds: Its lifetime.

    Returns:
        The token.
    """

    def part(value: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    return f"{part({'alg': 'none'})}.{part({'sub': 'someone', 'exp': int(time.time()) + seconds})}.{SIGNATURE}"


class Hub(http.server.BaseHTTPRequestHandler):
    """Serves a global model at `/outputs`, to callers with the token, and notes who asked."""

    token = ""
    status = 200
    location = ""
    seen: ClassVar[list[str]] = []

    def do_GET(self) -> None:
        """Serve the model, or refuse."""
        Hub.seen.append(self.headers.get("Authorization", ""))
        if Hub.location:
            self.send_response(302)
            self.send_header("Location", Hub.location)
            self.end_headers()
            return
        if Hub.status != 200 or self.headers.get("Authorization") != f"Bearer {Hub.token}":
            self.send_response(Hub.status if Hub.status != 200 else 401)
            self.end_headers()
            return
        body = b"model"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        """Keep quiet.

        Args:
            *args: Ignored.
        """


@contextlib.contextmanager
def hub(token: str, status: int = 200, location: str = "") -> Iterator[str]:
    """Run the fake hub on this host.

    Args:
        token: The token it takes.
        status: Status to answer with, if not the model.
        location: Where to redirect to, if anywhere.

    Yields:
        Its URL.
    """
    Hub.token, Hub.status, Hub.location, Hub.seen = token, status, location, []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Hub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


class Fixture(unittest.TestCase):
    """A fake CLI in a temporary folder, and the script's main() around it."""

    def setUp(self) -> None:
        """Write the fake CLI, and keep the environment."""
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.cli = self.tmp / "ga4gh-cli"
        self.cli.write_text(FAKE_CLI)
        self.cli.chmod(0o700)
        self.log = self.tmp / "calls.jsonl"
        self.scenario = self.tmp / "scenario.json"
        self.scenario.write_text("{}")
        environ = {"FAKE_CLI_LOG": str(self.log), "FAKE_CLI_SCENARIO": str(self.scenario), "RUST_LOG": "debug"}
        patcher = mock.patch.dict(os.environ, environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.token = make_token(3600)
        self.evaluated: list[list[str]] = []

    def calls(self) -> list[dict[str, Any]]:
        """Read what the fake CLI was called with.

        Returns:
            One entry per call.
        """
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def main(self, *extra: str, outputs: str = "", scenario: dict[str, Any] | None = None) -> tuple[int, str, str]:
        """Run main() with the token on standard input.

        Args:
            *extra: More arguments.
            outputs: The fake hub's URL, if any.
            scenario: What the fake CLI should do differently.

        Returns:
            Exit status, standard output and standard error.
        """
        self.scenario.write_text(json.dumps(scenario or {}))
        out = self.tmp / "row.md"
        argv = ["--wes", WES, "--cli", str(self.cli), "--token-stdin", "--interval", "0", "--out", str(out), *extra]
        if outputs:
            argv += ["--outputs-url", outputs]
        stdout, stderr = io.StringIO(), io.StringIO()

        def fake_evaluate(model: pathlib.Path, data: pathlib.Path, expect: str) -> tuple[bool, str]:
            self.evaluated.append([model.read_text(), expect])
            return True, "holdout accuracy: federated 0.975, site-1 alone 0.825, site-2 alone 0.875"

        with (
            mock.patch.object(sys, "stdin", io.StringIO(self.token + "\n")),
            mock.patch.object(sdk_run, "evaluate", fake_evaluate),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            status = sdk_run.main(argv)
        self.row = out.read_text() if out.exists() else ""
        return status, stdout.getvalue(), stderr.getvalue()


class RunTest(Fixture):
    """The whole script, against the fake CLI."""

    def test_complete_run(self) -> None:
        """A run that completes, through a gateway that ran each task where it was pinned."""
        with hub(self.token) as outputs:
            status, out, err = self.main("--gateway", GATEWAY, "--nodes", "A (site-1) and B (site-2)", outputs=outputs)
        self.assertEqual(status, 0, out + err)
        self.assertIn("run ID: 0123456789abcdef", out)
        self.assertIn("state: COMPLETE  (NVFlare job: FINISHED:COMPLETED)", out)
        self.assertIn(f"site-1: task task-1 COMPLETE at the WES; gateway: COMPLETE at {TES_1}, pinned: yes", out)
        self.assertIn(f"site-2: task task-2 COMPLETE at the WES; gateway: COMPLETE at {TES_2}, pinned: yes", out)
        self.assertIn("holdout accuracy: federated 0.975", out)
        self.assertEqual(self.evaluated, [["model", "0.975"]])
        self.assertTrue(self.row.startswith("| SDK run | A (site-1) and B (site-2) | "), self.row)
        self.assertIn("Run `01234567`", self.row)
        self.assertIn("site-1's task `COMPLETE`, at the TES it was pinned to", self.row)
        self.assertIn("Holdout accuracy: federated 0.975", self.row)
        self.assertNotIn("Failed", self.row)
        submitted = [call["argv"] for call in self.calls() if call["argv"][:2] == ["wes", "run"]]
        self.assertEqual(submitted[0][2:8], ["logreg-fedavg", "--type", "NVFLARE", "--type_version", "2.9", "--params"])
        self.assertEqual(json.loads(submitted[0][8]), {"sites": ["site-1", "site-2"]})

    def test_token_stays_out_of_arguments_and_files(self) -> None:
        """The CLI gets the token in its environment only; the row and the CLI's config never hold it."""
        with hub(self.token) as outputs:
            self.main("--gateway", GATEWAY, outputs=outputs)
        calls = self.calls()
        self.assertTrue(calls)
        for call in calls:
            self.assertEqual(call["token"], self.token)
            self.assertNotIn(SIGNATURE, json.dumps(call["argv"]))
            self.assertNotIn(SIGNATURE, call["config"])
            self.assertIn('"oauth_access_token_env": "NVFLARE_WES_SDK_TOKEN"', call["config"])
            self.assertIsNone(call["rust_log"])
        self.assertNotIn(SIGNATURE, self.row)
        for host in ("flare-wes.example.org", "gateway.example.org", "tes-1.example.org", "127.0.0.1"):
            self.assertNotIn(host, self.row)
        self.assertEqual(Hub.seen, [f"Bearer {self.token}"])

    def test_refused_submission(self) -> None:
        """A caller without the group's entitlement gets 403, and is told why."""
        status, _, err = self.main(scenario={"submit_status": 403})
        self.assertEqual(status, 1)
        self.assertIn("STOP: ga4gh-cli wes run failed: Error: HTTP status 403", err)
        self.assertIn("not in the group the WES requires", err)
        self.assertEqual(self.row, "")

    def test_failed_run(self) -> None:
        """A run that fails doesn't pass, and no model is fetched."""
        status, out, _ = self.main(scenario={"states": ["QUEUED", "SYSTEM_ERROR"]})
        self.assertEqual(status, 1)
        self.assertIn("[FAIL] the run ended SYSTEM_ERROR", out)
        self.assertIn("Failed: the run ended SYSTEM_ERROR", self.row)
        self.assertEqual(self.evaluated, [])

    def test_task_elsewhere(self) -> None:
        """A task that the gateway ran at another TES than its pin fails the run's checks."""
        with hub(self.token) as outputs:
            status, out, _ = self.main("--gateway", GATEWAY, outputs=outputs, scenario={"ran": {"task-2": TES_1}})
        self.assertEqual(status, 1)
        self.assertIn("[FAIL] the task of site-2 didn't run at the TES it was pinned to", out)
        self.assertIn("site-2's task `COMPLETE`, NOT at the TES it was pinned to", self.row)

    def test_gateway_hides_tasks(self) -> None:
        """A gateway that doesn't show the tasks to this caller leaves pinning unknown, but doesn't fail."""
        with hub(self.token) as outputs:
            status, out, _ = self.main("--gateway", GATEWAY, outputs=outputs, scenario={"tes_status": 404})
        self.assertEqual(status, 0, out)
        self.assertIn("site-1: task task-1 COMPLETE at the WES (the gateway didn't show the task", out)
        self.assertIn("site-1's task `COMPLETE`, where it ran unknown", self.row)

    def test_model_out_of_reach(self) -> None:
        """Without a route to /outputs, the script says how to fetch the model."""
        with hub(self.token, status=503) as outputs:
            status, out, _ = self.main(outputs=outputs)
        self.assertEqual(status, 1)
        self.assertIn("couldn't be fetched (HTTP 503)", out)
        self.assertIn("--run-id 0123456789abcdef --outputs-url http://localhost:8080", out)
        self.assertIn("Failed: the global model couldn't be fetched (HTTP 503).", self.row)

    def test_garbage_from_the_cli(self) -> None:
        """Something else than JSON from the CLI stops the script with a message, not a traceback."""
        status, _, err = self.main(scenario={"garbage": True})
        self.assertEqual(status, 1)
        self.assertIn("STOP: ga4gh-cli service-info --service printed no JSON object: <html>", err)

    def test_token_echoed_by_the_cli(self) -> None:
        """A token that the CLI or a server echoes in an error doesn't reach the output."""
        status, out, err = self.main(scenario={"echo_token": True})
        self.assertEqual(status, 1)
        self.assertIn("Authorization: Bearer ***", err)
        self.assertNotIn(SIGNATURE, out + err)

    def test_task_without_pin(self) -> None:
        """A task without a gateway.backends tag can't be checked, and says so."""
        with hub(self.token) as outputs:
            for pin in (None, {"type": "deny", "backends": [TES_1]}, {"type": "allow", "backends": TES_1 + "/x"}):
                with self.subTest(pin=pin):
                    status, out, _ = self.main("--gateway", GATEWAY, outputs=outputs, scenario={"pin": pin})
                    self.assertEqual(status, 0, out)
                    self.assertIn("pinned: - (the task has no gateway.backends tag that allows a list of TES", out)

    def test_model_redirect_refused(self) -> None:
        """A redirect from /outputs isn't followed, so the token goes nowhere else."""
        with hub(self.token, location="https://elsewhere.example.org/model") as outputs:
            status, out, _ = self.main(outputs=outputs)
        self.assertEqual(status, 1)
        self.assertIn("couldn't be fetched (HTTP 302)", out)
        self.assertEqual(len(Hub.seen), 1)

    def test_follow_existing_run(self) -> None:
        """--run-id follows a run without submitting one."""
        with hub(self.token) as outputs:
            status, _, _ = self.main("--run-id", "0123456789abcdef", outputs=outputs)
        self.assertEqual(status, 0)
        self.assertFalse([call for call in self.calls() if call["argv"][:2] == ["wes", "run"]])
        self.assertIn(
            "access token: `COMPLETE`, started 2026-11-29T10:00:00Z, ended 2026-11-29T10:01:32Z by the WES's run log.",
            self.row,
        )

    def test_port_forward_bypasses_proxies(self) -> None:
        """The model goes straight to a port forward on this host, not through a proxy of the environment."""
        with (
            hub(self.token) as outputs,
            mock.patch.dict(os.environ, {"http_proxy": "http://127.0.0.1:9", "no_proxy": ""}),
        ):
            status, out, _ = self.main(outputs=outputs)
        self.assertEqual(status, 0, out)

    def test_timeout(self) -> None:
        """A run that doesn't end in time fails, and says how to pick it up."""
        status, out, _ = self.main("--timeout", "0", scenario={"states": ["RUNNING"]})
        self.assertEqual(status, 1)
        self.assertIn(
            "[FAIL] no final state after 0 s (last RUNNING)\n  -> follow the run again later with --run-id", out
        )
        self.assertNotIn("ended RUNNING", out + self.row)
        self.assertFalse([call for call in self.calls() if call["argv"][:2] == ["wes", "get"]])

    def test_status_retried(self) -> None:
        """A failed status request is tried again, and the run followed to its end."""
        with hub(self.token) as outputs, mock.patch("time.sleep"):
            status, out, _ = self.main(outputs=outputs, scenario={"status_failures": 2})
        self.assertEqual(status, 0, out)

    def test_status_lost(self) -> None:
        """Status requests that keep failing end following, with a row and a hint, not a traceback."""
        with mock.patch("time.sleep"):
            status, out, err = self.main(scenario={"status_failures": 99})
        self.assertEqual(status, 1, err)
        self.assertIn(
            "[FAIL] the run's state couldn't be read (ga4gh-cli wes status failed: Error: HTTP status 502)", out
        )
        self.assertIn("-> follow the run again later with --run-id 0123456789abcdef", out)
        self.assertIn("own access token: state not read. Failed: the run's state couldn't be read", self.row)

    def test_log_lost(self) -> None:
        """A run log that can't be read after the run's end gives a row and a hint, not just STOP."""
        with mock.patch("time.sleep"):
            status, out, _ = self.main(scenario={"get_status": 502})
        self.assertEqual(status, 1)
        self.assertIn("[FAIL] the run's log couldn't be read (ga4gh-cli wes get failed: Error: HTTP status 502)", out)
        self.assertIn("-> follow the run again later with --run-id 0123456789abcdef", out)
        self.assertIn("`COMPLETE`", self.row)

    def test_unknown_site(self) -> None:
        """Sites the hub doesn't have are refused before submitting."""
        status, _, err = self.main("--sites", "site-1,site-9")
        self.assertEqual(status, 1)
        self.assertIn("the hub has the sites ['site-1', 'site-2'], not ['site-1', 'site-9']", err)

    def test_expired_token(self) -> None:
        """A token about to expire is refused before anything is called."""
        self.token = make_token(60)
        status, _, err = self.main()
        self.assertEqual(status, 1)
        self.assertIn("the token expires in", err)
        self.assertEqual(self.calls(), [])


class PartsTest(unittest.TestCase):
    """The script's parts on their own."""

    def test_urls(self) -> None:
        """Tokens go over HTTPS, or plain HTTP to this host only."""
        sdk_run.check_url(WES)
        sdk_run.check_url("http://localhost:8080")
        sdk_run.check_url("http://127.0.0.1:8080/ga4gh/wes/v1")
        sdk_run.check_url("http://hub:8080/ga4gh/wes/v1", allow_http=True)
        for url in ("http://hub:8080/ga4gh/wes/v1", "ftp://x.org", "https://u:p@x.org", "https://x.org/?a=1", "x"):
            with self.subTest(url=url), self.assertRaises(sdk_run.Stop):
                sdk_run.check_url(url)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            sdk_run.parse_args(["--wes", "http://hub:8080/ga4gh/wes/v1"])

    def test_read_token(self) -> None:
        """The token comes from the prompt or standard input, without a `Bearer ` prefix."""
        self.assertEqual(sdk_run.read_token(False, prompt=lambda _: " abc \n"), "abc")
        self.assertEqual(sdk_run.read_token(True, stdin=io.StringIO("Bearer abc\nmore\n")), "abc")
        for value in ("", "a b"):
            with self.subTest(value=value), self.assertRaises(sdk_run.Stop):
                sdk_run.read_token(True, stdin=io.StringIO(value))

    def test_token_lifetime(self) -> None:
        """The lifetime comes from `exp`; tokens that aren't JWTs have none."""
        self.assertAlmostEqual(sdk_run.token_seconds_left(make_token(100)) or 0, 100, delta=2)
        self.assertIsNone(sdk_run.token_seconds_left("opaque"))
        self.assertIsNone(sdk_run.token_seconds_left("a.b.c"))

    def test_secret_free(self) -> None:
        """A results row with the token, a host name or a URL isn't written."""
        sdk_run.check_secret_free("| SDK run | x |", "tok", [WES, ""])
        for text in ("tok", "flare-wes.example.org", "see https://elsewhere.org"):
            with self.subTest(text=text), self.assertRaises(sdk_run.Stop):
                sdk_run.check_secret_free(text, "tok", [WES])

    def test_outputs_base(self) -> None:
        """/outputs is next to the WES's API root."""
        self.assertEqual(sdk_run.outputs_base(WES), "https://flare-wes.example.org")

    def test_refusal_hints(self) -> None:
        """Hints go by the HTTP status the CLI names, not by any number in the message."""
        self.assertIn("expired", sdk_run.explain_refusal("Request failed with status: 401 Unauthorized"))
        self.assertIn("another run", sdk_run.explain_refusal("Error: HTTP status 409"))
        self.assertEqual(sdk_run.explain_refusal("run 0403 failed: status: 500"), "run 0403 failed: status: 500")

    def test_config_is_private(self) -> None:
        """The CLI's folder and file are for this user only, and name the token's variable only."""
        with tempfile.TemporaryDirectory() as tmp:
            sdk_run.write_config(pathlib.Path(tmp), WES, GATEWAY)
            folder = pathlib.Path(tmp) / ".ga4gh-cli"
            self.assertEqual(folder.stat().st_mode & 0o777, 0o700)
            self.assertEqual((folder / "config.json").stat().st_mode & 0o777, 0o600)
            config = json.loads((folder / "config.json").read_text())
        self.assertEqual(config["WES"]["oauth_access_token_env"], sdk_run.TOKEN_ENV)
        self.assertEqual(config["TES"]["base_path"], GATEWAY)

    def test_download_checksum(self) -> None:
        """A downloaded CLI whose checksum doesn't match isn't unpacked or run."""
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch("urllib.request.urlopen", return_value=io.BytesIO(b"not the release")),
            mock.patch.object(sdk_run, "cli_asset", return_value=("cli.tar.gz", "0" * 64)),
            self.assertRaisesRegex(sdk_run.Stop, "checksum of cli.tar.gz doesn't match"),
        ):
            sdk_run.download_cli(pathlib.Path(tmp))

    def test_download(self) -> None:
        """A release whose checksum matches is unpacked, and its CLI made executable."""
        with tempfile.TemporaryDirectory() as tmp:
            folder = pathlib.Path(tmp)
            (folder / "src").mkdir()
            (folder / "src" / "ga4gh-cli").write_text("#!/bin/sh\n")
            with tarfile.open(folder / "release.tar.gz", "w:gz") as tar:
                tar.add(folder / "src" / "ga4gh-cli", arcname="ga4gh-cli-x/ga4gh-cli")
            data = (folder / "release.tar.gz").read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            (folder / "out").mkdir()
            with (
                mock.patch("urllib.request.urlopen", return_value=io.BytesIO(data)),
                mock.patch.object(sdk_run, "cli_asset", return_value=("cli.tar.gz", digest)),
            ):
                cli = sdk_run.download_cli(folder / "out")
            self.assertEqual(cli.name, "ga4gh-cli")
            self.assertTrue(os.access(cli, os.X_OK))

    def test_evaluate_command(self) -> None:
        """NumPy of this Python first, then uv, else none."""
        found = mock.Mock(returncode=0)
        missing = mock.Mock(returncode=1)
        with mock.patch("subprocess.run", return_value=found):
            self.assertEqual(sdk_run.evaluate_command(), [sys.executable])
        with mock.patch("subprocess.run", return_value=missing), mock.patch("shutil.which", return_value="/bin/uv"):
            self.assertEqual(sdk_run.evaluate_command()[:2], ["/bin/uv", "run"])
        with mock.patch("subprocess.run", return_value=missing), mock.patch("shutil.which", return_value=None):
            self.assertIsNone(sdk_run.evaluate_command())
            passed, output = sdk_run.evaluate(pathlib.Path("m.npy"), pathlib.Path("data"), "0.975")
        self.assertFalse(passed)
        self.assertIn("no Python with NumPy, and no uv", output)

    def test_cli_asset(self) -> None:
        """Each supported machine has a checksum; others are told to pass --cli."""
        with mock.patch("platform.system", return_value="Linux"), mock.patch("platform.machine", return_value="x86_64"):
            self.assertEqual(sdk_run.cli_asset()[0], "ga4gh-cli-0.1.0-x86_64-unknown-linux-gnu.tar.gz")
        with (
            mock.patch("platform.system", return_value="Plan9"),
            mock.patch("platform.machine", return_value="mips"),
            self.assertRaises(sdk_run.Stop),
        ):
            sdk_run.cli_asset()


if __name__ == "__main__":
    unittest.main()

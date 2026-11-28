#!/usr/bin/env python3
"""Run a federated job from the GA4GH SDK CLI, with a user's own token (#73).

Submits `logreg-fedavg` (`NVFLARE`, version 2.9) to a hub's WES with the GA4GH
SDK's CLI (`ga4gh-cli`), follows the run to a final state, and prints the run
ID, its state, what each site's task did and the holdout accuracy of the
global model. With `--gateway`, it asks the TES gateway (proTES) with the same
token where each client task ran, and whether that is the TES its site is
pinned to. At the end, it writes a row for `docs/outcomes/results.md`, without
the token or any host name.

The token is read without echo from the terminal (or, with `--token-stdin`,
from standard input), never from the command line, and goes to the CLI only in
its environment, never in its arguments. The CLI's configuration lives in a
temporary folder, which is removed at the end: `~/.ga4gh-cli` isn't touched.
Without `--cli`, the CLI is downloaded from its release and checked against
the checksum below.

Needs Python 3.12 or later, and no packages. The holdout accuracy needs NumPy,
or `uv` to get it: without either, the script says how to evaluate the model.

Usage (any shell):

    python3 scripts/sdk_run.py --wes https://<hub>/ga4gh/wes/v1 \\
        --gateway https://<proTES>/ga4gh/tes/v1 --sites site-1,site-2

Exit status: 0 if the run ended `COMPLETE` and every check passed, 1 if not,
2 for wrong arguments.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import http.client
import ipaddress
import json
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

REPO = pathlib.Path(__file__).resolve().parent.parent
CLI_VERSION = "0.1.0"
CLI_RELEASE = f"https://github.com/ga4gh/ga4gh-sdk/releases/download/v{CLI_VERSION}"
# From the release's SHA256SUMS, so that a changed asset is refused
CLI_SHA256 = {
    ("Linux", "x86_64"): (
        "x86_64-unknown-linux-gnu",
        "9c5892e89b302b1d95522d568672288ad466c9779b3c6aeea8118750fb7f625d",
    ),
    ("Linux", "aarch64"): (
        "aarch64-unknown-linux-gnu",
        "b26eca0e14806330731902484696d7e9d1df01bdefd366ef5b6765c2aa7620bb",
    ),
    ("Linux", "arm64"): (
        "aarch64-unknown-linux-gnu",
        "b26eca0e14806330731902484696d7e9d1df01bdefd366ef5b6765c2aa7620bb",
    ),
    ("Darwin", "x86_64"): ("x86_64-apple-darwin", "a6dd3179b490dacc4a25d82db5f9aecdd020ef596ed386d9d0c51add18c5e1ba"),
    ("Darwin", "arm64"): ("aarch64-apple-darwin", "599e7cddc7a06bcc6b97f3dce96b202e4153ede7a79424d92210e5b351f38844"),
}
# The variable through which the CLI gets the token (`oauth_access_token_env`)
TOKEN_ENV = "NVFLARE_WES_SDK_TOKEN"
TERMINAL = ("COMPLETE", "EXECUTOR_ERROR", "SYSTEM_ERROR", "CANCELED")
# Below this, a run of about two minutes, and fetching its model, may not fit
MIN_TOKEN_SECONDS = 300
CLI_TIMEOUT = 180


class Stop(Exception):
    """A problem that ends the script, with what to do about it."""


@dataclass
class SiteTask:
    """What is known about the task of one site.

    Attributes:
        site: Name of the site.
        task_id: The task's ID at the hub's TES or gateway.
        state: The task's state in the WES run log.
        gateway_state: The task's state at the gateway, if asked.
        backend: The TES that the gateway sent it to, if asked.
        pinned: Whether that is the TES of the task's `gateway.backends` tag,
            `None` if unknown.
        note: Why the gateway couldn't tell, if it couldn't.
    """

    site: str
    task_id: str
    state: str
    gateway_state: str = ""
    backend: str = ""
    pinned: bool | None = None
    note: str = ""


@dataclass
class Outcome:
    """What a run came to, for the summary and the results row.

    Attributes:
        run_id: ID of the run.
        state: Final (or last seen) state of the run.
        seen: First time each state was seen, as `HH:MM:SS` UTC.
        seconds: Seconds from submission to the last state seen.
        job_status: NVFlare's job status, from the run's outputs.
        tasks: The tasks of the sites.
        accuracy: The evaluation's line of accuracies, if any.
        failures: Checks that failed, as they go into the results row.
        hints: What to do about them, printed but kept out of the row.
        picked_up: Whether the run was submitted earlier (`--run-id`), so
            that the states seen aren't its timeline.
        wes_times: Start and end of the run, from the WES's run log.
    """

    run_id: str
    state: str = ""
    seen: dict[str, str] = field(default_factory=dict)
    seconds: float = 0.0
    job_status: str = ""
    tasks: list[SiteTask] = field(default_factory=list)
    accuracy: str = ""
    failures: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    picked_up: bool = False
    wes_times: tuple[str, str] = ("", "")


STATUS_TRIES = 4
# Larger answers are refused rather than read into memory
MAX_CLI_BYTES = 256 * 1024 * 1024
MAX_MODEL_BYTES = 16 * 1024 * 1024


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the command line.

    Args:
        argv: Arguments, without the program's name; `sys.argv` if `None`.

    Returns:
        The options.
    """
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--wes", required=True, help="The hub's WES API root, such as https://<hub>/ga4gh/wes/v1")
    parser.add_argument(
        "--gateway",
        default="",
        help="The TES gateway's API root (proTES), to check where each task ran; asked with the same token",
    )
    parser.add_argument(
        "--sites", default="site-1,site-2", help="Sites of the run, comma-separated (default: %(default)s)"
    )
    parser.add_argument(
        "--job",
        default="",
        help="Job in the hub's image (default: logreg-fedavg for two sites, logreg-fedavg-<n> for n)",
    )
    parser.add_argument(
        "--run-id",
        default="",
        help="Follow and evaluate this run instead of submitting one, e.g. after a timeout or to fetch its model",
    )
    parser.add_argument(
        "--timeout", type=int, default=1200, help="Seconds to wait for a final state (default: %(default)s)"
    )
    parser.add_argument(
        "--interval", type=float, default=10, help="Seconds between status requests (default: %(default)s)"
    )
    parser.add_argument(
        "--outputs-url",
        default="",
        help=(
            "Where the hub serves /outputs, if not at the WES's origin, such as http://localhost:8080 through "
            "a port forward: on Rahti, only /ga4gh/wes/v1 is routed"
        ),
    )
    parser.add_argument(
        "--data", type=pathlib.Path, default=REPO / "testset" / "data", help="The test set, for the holdout accuracy"
    )
    parser.add_argument(
        "--expect", default="0.975", help="Federated accuracy to expect, or '' for none (default: %(default)s)"
    )
    parser.add_argument("--nodes", default="<Nodes>", help="What goes into the results row's Node column")
    parser.add_argument("--out", type=pathlib.Path, help="File for the results row (default: sdk-run-<run>.md here)")
    parser.add_argument("--cli", type=pathlib.Path, help=f"A ga4gh-cli to use instead of downloading {CLI_VERSION}")
    parser.add_argument(
        "--token-stdin", action="store_true", help="Read the token from standard input, not the terminal"
    )
    parser.add_argument(
        "--allow-http",
        action="store_true",
        help="Allow plain HTTP to hosts other than this one (tests only: the token would go unencrypted)",
    )
    args = parser.parse_args(argv)
    args.sites = [site.strip() for site in args.sites.split(",") if site.strip()]
    if not args.sites:
        parser.error("--sites names no site")
    if not args.job:
        args.job = "logreg-fedavg" if len(args.sites) == 2 else f"logreg-fedavg-{len(args.sites)}"
    for name in ("wes", "gateway", "outputs_url"):
        value = getattr(args, name)
        if value:
            try:
                check_url(value, args.allow_http)
            except Stop as error:
                parser.error(f"--{name.replace('_', '-')}: {error}")
    return args


def check_url(url: str, allow_http: bool = False) -> None:
    """Refuse URLs that would send the token in the clear, or that carry credentials.

    Args:
        url: The URL.
        allow_http: Whether plain HTTP is fine to any host.

    Raises:
        Stop: The URL isn't HTTPS (or HTTP to this host), or has userinfo, a
            query or a fragment.
    """
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise Stop(f"not an HTTP(S) URL: {url}")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise Stop("no user, password, query or fragment in the URL, please")
    if parts.scheme == "http" and not allow_http and not is_loopback(parts.hostname):
        raise Stop("plain HTTP only to this host (localhost), as the token goes along")


def is_loopback(host: str) -> bool:
    """Tell whether a host name is this host.

    Args:
        host: Host name or address.

    Returns:
        Whether it is `localhost` or a loopback address.
    """
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def read_token(from_stdin: bool, stdin: Any = None, prompt: Callable[[str], str] = getpass.getpass) -> str:
    """Read the access token without showing it.

    Args:
        from_stdin: Read the first line of standard input instead of asking at the terminal.
        stdin: Standard input; `sys.stdin` if `None`.
        prompt: Asks for a secret at the terminal, without echo.

    Returns:
        The token.

    Raises:
        Stop: No token, or one with spaces in it.
    """
    if from_stdin:
        token = (stdin or sys.stdin).readline().strip()
    else:
        token = prompt("LS Login access token (not shown), then Enter: ").strip()
    token = token.removeprefix("Bearer ").strip()
    if not token:
        raise Stop("no token")
    if any(char.isspace() for char in token):
        raise Stop("the token has spaces in it: paste the access token alone")
    return token


def token_seconds_left(token: str, now: float | None = None) -> int | None:
    """Read how long a JWT access token still lives, without checking it.

    Args:
        token: The token.
        now: The current time; `time.time()` if `None`.

    Returns:
        Seconds until `exp`, or `None` if the token isn't a JWT with `exp`.
    """
    try:
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return int(claims["exp"] - (time.time() if now is None else now))
    except (IndexError, ValueError, KeyError, TypeError):
        return None


def cli_asset() -> tuple[str, str]:
    """Name the CLI's release asset for this machine, and its checksum.

    Returns:
        The asset's file name and its SHA-256.

    Raises:
        Stop: No release asset for this machine.
    """
    key = (platform.system(), platform.machine())
    if key not in CLI_SHA256:
        raise Stop(f"no ga4gh-cli {CLI_VERSION} for {key}: build it and pass --cli")
    target, digest = CLI_SHA256[key]
    return f"ga4gh-cli-{CLI_VERSION}-{target}.tar.gz", digest


def save_bounded(reply: Any, path: pathlib.Path, limit: int) -> None:
    """Save a response in chunks, up to a size.

    Args:
        reply: The response, with `read(size)`.
        path: Where to save it.
        limit: The most bytes to take.

    Raises:
        Stop: The response is larger.
    """
    size = 0
    with path.open("wb") as file:
        while chunk := reply.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                raise Stop(f"the answer is larger than {limit // (1024 * 1024)} MiB: not taking it")
            file.write(chunk)


def download_cli(folder: pathlib.Path) -> pathlib.Path:
    """Download the CLI's release for this machine, and check its checksum.

    Args:
        folder: Where to put it.

    Returns:
        Path of the executable.

    Raises:
        Stop: The download failed, or the checksum doesn't match.
    """
    asset, digest = cli_asset()
    archive = folder / asset
    try:
        with urllib.request.urlopen(f"{CLI_RELEASE}/{asset}", timeout=120) as reply:  # a fixed HTTPS URL
            save_bounded(reply, archive, MAX_CLI_BYTES)
    except (urllib.error.URLError, OSError) as error:
        raise Stop(f"download of {asset} failed: {error}") from None
    if hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
        raise Stop(f"checksum of {asset} doesn't match: not running it")
    with tarfile.open(archive) as tar:
        tar.extractall(folder / "cli", filter="data")
    found = [path for path in (folder / "cli").rglob("ga4gh-cli") if path.is_file()]
    if not found:
        raise Stop(f"no ga4gh-cli in {asset}")
    found[0].chmod(0o700)
    return found[0]


def write_config(home: pathlib.Path, wes: str, gateway: str) -> None:
    """Write the CLI's configuration, which names the token's variable but not the token.

    Args:
        home: The CLI's home folder.
        wes: The WES's API root.
        gateway: The gateway's API root, or empty.
    """
    folder = home / ".ga4gh-cli"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    section = {"oauth_access_token_env": TOKEN_ENV, "timeouts": {"submission": 120, "request": 60}}
    config: dict[str, Any] = {"WES": {"base_path": wes, **section}}
    if gateway:
        config["TES"] = {"base_path": gateway, **section}
    path = folder / "config.json"
    path.touch(mode=0o600)
    path.write_text(json.dumps(config, indent=2) + "\n")


class Cli:
    """Runs `ga4gh-cli` with its own home folder and the token in its environment only."""

    def __init__(self, executable: pathlib.Path, home: pathlib.Path, token: str) -> None:
        """Set up the environment of the CLI.

        Args:
            executable: The CLI.
            home: Its home folder, with its configuration.
            token: The access token.
        """
        self.executable = executable
        self.token = token
        drop = ("GA4GH_CLI_PROFILE", "RUST_LOG")
        self.env = {key: value for key, value in os.environ.items() if key not in drop}
        self.env.update({"HOME": str(home), TOKEN_ENV: token})

    def __call__(self, *args: str) -> str:
        """Run a command of the CLI.

        Args:
            *args: Its arguments.

        Returns:
            What it printed on standard output.

        Raises:
            Stop: It failed; with what it printed on standard error.
        """
        try:
            # An argument list, no shell; the CLI is checked against its checksum, or given by the user
            # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit.dangerous-subprocess-use-audit
            done = subprocess.run(
                [str(self.executable), *args],
                env=self.env,
                capture_output=True,
                text=True,
                timeout=CLI_TIMEOUT,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise Stop(f"ga4gh-cli {' '.join(args[:2])} took over {CLI_TIMEOUT} s") from None
        except OSError as error:
            raise Stop(f"ga4gh-cli can't be run ({error.strerror}): check --cli") from None
        if done.returncode != 0:
            error = scrub(done.stderr.strip(), self.token) or done.returncode
            raise Stop(f"ga4gh-cli {' '.join(args[:2])} failed: {error}")
        return done.stdout.strip()

    def json(self, *args: str) -> dict[str, Any]:
        """Run a command of the CLI that prints a JSON object.

        Args:
            *args: Its arguments.

        Returns:
            The object.

        Raises:
            Stop: It failed, or printed something else.
        """
        out = self(*args)
        try:
            value = json.loads(out)
        except ValueError:
            value = None
        if not isinstance(value, dict):
            raise Stop(f"ga4gh-cli {' '.join(args[:2])} printed no JSON object: {scrub(out, self.token)[:200]}")
        return value


def scrub(text: str, token: str) -> str:
    """Hide the token in a text, should a server or the CLI echo it.

    Args:
        text: The text.
        token: The token.

    Returns:
        The text, with `***` for the token.
    """
    return text.replace(token, "***") if token else text


def explain_refusal(message: str) -> str:
    """Add what to do to the CLI's error for a refused submission.

    Args:
        message: The error.

    Returns:
        The error, with a hint for 401, 403 and 409.
    """
    status = re.search(r"\bstatus:? (\d{3})\b", message)
    hints = {
        "401": "the WES didn't take the token: expired, or not for the WES's audience (take it from the portal)",
        "403": "the token is fine, but its owner may not start runs: not in the group the WES requires",
        "409": "another run is active at the hub: wait for it to end",
    }
    if status and status.group(1) in hints:
        return f"{message}\n  -> {hints[status.group(1)]}"
    return message


def submit(cli: Cli, job: str, sites: list[str]) -> str:
    """Submit the run.

    Args:
        cli: The CLI.
        job: The job's name.
        sites: The sites.

    Returns:
        The run's ID.

    Raises:
        Stop: The WES refused it.
    """
    try:
        answer = cli.json(
            "wes",
            "run",
            job,
            "--type",
            "NVFLARE",
            "--type_version",
            "2.9",
            "--params",
            json.dumps({"sites": sites}),
            "--tag",
            "submitted_with=ga4gh-cli",
            "--format",
            "json",
        )
    except Stop as error:
        message = explain_refusal(str(error))
        if not re.search(r"\bstatus:? 4\d\d\b", message):
            # Not refused: the WES may have taken it, and the answer got lost
            message += "\n  -> the WES may have started the run anyway; your runs there:\n" + list_runs(cli)
        raise Stop(message) from None
    run_id = answer.get("run_id", "")
    if not run_id:
        raise Stop(f"no run ID in the WES's answer: {answer}")
    return str(run_id)


def list_runs(cli: Cli) -> str:
    """List the caller's runs at the WES, for picking one up with `--run-id`.

    Args:
        cli: The CLI.

    Returns:
        The list, or why there is none.
    """
    try:
        return cli("wes", "list")
    except Stop as error:
        return f"(couldn't list them: {error})"


def retried(call: Callable[[], Any], sleep: Callable[[float], None], left: Callable[[], float] | None = None) -> Any:
    """Call something that may fail for a moment, a few times, with growing pauses.

    Args:
        call: What to call.
        sleep: Waits for some seconds.
        left: Seconds left for trying; no limit if `None`.

    Returns:
        What it returned.

    Raises:
        Stop: It failed every time; the last failure.
    """
    for attempt in range(STATUS_TRIES - 1):
        try:
            return call()
        except Stop:
            pause = 5 * 2**attempt
            if left is not None and left() < pause:
                raise
            sleep(pause)
    return call()


def follow(
    cli: Cli,
    outcome: Outcome,
    timeout: float,
    interval: float,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] | None = None,
) -> None:
    """Poll the run's state until it is final, or the time is up.

    Args:
        cli: The CLI.
        outcome: The run's outcome, whose states this fills in.
        timeout: Seconds to wait.
        interval: Seconds between requests.
        clock: Monotonic clock.
        sleep: Waits for some seconds; `time.sleep` if `None`.
    """
    sleep = sleep or time.sleep
    start = clock()
    while True:
        try:
            state = retried(lambda: cli("wes", "status", outcome.run_id), sleep, lambda: timeout - (clock() - start))
        except Stop as error:
            outcome.failures.append(f"the run's state couldn't be read ({explain_refusal(str(error))})")
            outcome.hints.append(f"follow the run again later with --run-id {outcome.run_id}")
            return
        outcome.seconds = clock() - start
        if state not in outcome.seen:
            outcome.seen[state] = time.strftime("%H:%M:%S", time.gmtime())
            print(f"{outcome.seen[state]} UTC  {outcome.seconds:5.0f} s  {state}", flush=True)
        outcome.state = state
        if state in TERMINAL:
            return
        if clock() - start >= timeout:
            outcome.failures.append(f"no final state after {timeout:.0f} s (last {state})")
            outcome.hints.append(f"follow the run again later with --run-id {outcome.run_id}")
            return
        sleep(interval)


def site_tasks(log: dict[str, Any]) -> list[SiteTask]:
    """Pick the client tasks of the sites from a run log.

    Args:
        log: The WES run log.

    Returns:
        One entry per client task, by site.
    """
    tasks = []
    for task in log.get("task_logs") or []:
        name = str(task.get("name", ""))
        if name.startswith("fl-client "):
            logs = task.get("system_logs") or [""]
            tasks.append(
                SiteTask(site=name.removeprefix("fl-client "), task_id=str(task.get("id", "")), state=str(logs[-1]))
            )
    return sorted(tasks, key=lambda task: task.site)


def check_pinning(cli: Cli, task: SiteTask) -> None:
    """Ask the gateway where a task ran, and whether that's where it was pinned.

    Args:
        cli: The CLI, with the gateway as its TES.
        task: The task, whose gateway fields this fills in.
    """
    try:
        record = cli.json("tes", "get", task.task_id, "BASIC")
    except Stop as error:
        task.note = f"the gateway didn't show the task ({error}); it's visible to its submitter at the gateway only"
        return
    tags = record.get("tags") or {}
    task.gateway_state = str(record.get("state", ""))
    task.backend = str(tags.get("gateway.backend", ""))
    try:
        pin = json.loads(tags.get("gateway.backends", ""))
    except (ValueError, TypeError):
        pin = None
    allowed = pin.get("backends") if isinstance(pin, dict) and pin.get("type") == "allow" else None
    if not isinstance(allowed, list):
        task.note = "the task has no gateway.backends tag that allows a list of TES to check against"
        return
    task.pinned = bool(task.backend) and task.backend in allowed


def evaluate_command() -> list[str] | None:
    """Find a Python with NumPy for `testset/evaluate.py`.

    Returns:
        The command to run Python with, or `None` if there's none.
    """
    # This Python, with fixed arguments
    # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit.dangerous-subprocess-use-audit
    probe = subprocess.run([sys.executable, "-c", "import numpy"], capture_output=True, check=False)
    if probe.returncode == 0:
        return [sys.executable]
    uv = shutil.which("uv")
    if uv:
        return [uv, "run", "--no-project", "--quiet", "--with", "numpy>=1.26,<3", "python3"]
    return None


class NoRedirects(urllib.request.HTTPRedirectHandler):
    """Refuses redirects, so that the token goes nowhere else.

    As in `tests/outside_check.py`, on purpose a copy: the script needs no other file.
    """

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        """Refuse to follow.

        Args:
            *args: Ignored.
            **kwargs: Ignored.
        """


def fetch_model(outputs_url: str, run_id: str, token: str, path: pathlib.Path) -> str:
    """Download a run's global model.

    Args:
        outputs_url: Where the hub serves `/outputs`.
        run_id: ID of the run.
        token: The access token.
        path: Where to put the model.

    Returns:
        Empty if it worked, otherwise what went wrong.
    """
    request = urllib.request.Request(
        f"{outputs_url.rstrip('/')}/outputs/{urllib.parse.quote(run_id, safe='')}/global_model.npy",
        headers={"Authorization": f"Bearer {token}"},
    )
    handlers: list[Any] = [NoRedirects]
    if is_loopback(urllib.parse.urlsplit(outputs_url).hostname or ""):
        # Straight to a port forward, never through a proxy from the environment
        handlers.append(urllib.request.ProxyHandler({}))
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(request, timeout=60) as reply:
            save_bounded(reply, path, MAX_MODEL_BYTES)
    except urllib.error.HTTPError as error:
        return f"HTTP {error.code}"
    except Stop as error:
        return str(error)
    except (urllib.error.URLError, OSError, http.client.HTTPException) as error:
        return str(getattr(error, "reason", error))
    return ""


def evaluate(model: pathlib.Path, data: pathlib.Path, expect: str) -> tuple[bool, str]:
    """Compute the holdout accuracy of a global model with `testset/evaluate.py`.

    Args:
        model: The model.
        data: The test set.
        expect: Federated accuracy to expect, or empty.

    Returns:
        Whether the evaluation passed, and its output.
    """
    python = evaluate_command()
    if python is None:
        return False, "no Python with NumPy, and no uv: install NumPy or uv, then run again with --run-id"
    expect_args = ["--expect", expect] if expect else []
    try:
        # An argument list, no shell: the repository's own script, with this run's paths
        # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit.dangerous-subprocess-use-audit
        done = subprocess.run(
            [*python, str(REPO / "testset" / "evaluate.py"), str(model), "--data", str(data), *expect_args],
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "the evaluation took over 600 s"
    return done.returncode == 0, (done.stdout + done.stderr).strip()


def outputs_base(wes: str) -> str:
    """Derive where the hub serves `/outputs` from its WES's API root.

    Args:
        wes: The WES's API root.

    Returns:
        The origin and path before `/ga4gh/`.
    """
    return wes.split("/ga4gh/", 1)[0]


def results_row(outcome: Outcome, nodes: str, gateway_checked: bool, today: str | None = None) -> str:
    """Write the row for `docs/outcomes/results.md`, without token or host names.

    Args:
        outcome: What the run came to.
        nodes: The Node column.
        gateway_checked: Whether the gateway was asked where tasks ran.
        today: The date, `YYYY-MM-DD`; today in UTC if `None`.

    Returns:
        The row, as one line of Markdown.
    """
    start, end = outcome.wes_times
    run = f"Run `{outcome.run_id[:8]}`, submitted with the GA4GH SDK CLI {CLI_VERSION} and the submitter's own access token"
    if outcome.picked_up:
        # The states were seen later, not as they happened: the WES's own times only
        times = f"started {start or '?'}, ended {end or '?'} by the WES's run log"
        sentences = [f"{run}: `{outcome.state or 'state not read'}`, {times}"]
    else:
        states = ", ".join(f"`{state}` {seen}" for state, seen in outcome.seen.items())
        sentences = [f"{run}: {states} UTC, about {outcome.seconds:.0f} s" if states else f"{run}: state not read"]
    if outcome.job_status:
        sentences.append(f"NVFlare job `{outcome.job_status}`")
    tasks = []
    for task in outcome.tasks:
        where = ""
        if task.pinned is True:
            where = ", at the TES it was pinned to"
        elif task.pinned is False:
            where = ", NOT at the TES it was pinned to"
        elif gateway_checked:
            where = ", where it ran unknown"
        tasks.append(f"{task.site}'s task `{task.state}`{where}")
    if tasks:
        sentences.append("; ".join(tasks))
    if outcome.accuracy:
        sentences.append(f"Holdout accuracy: {outcome.accuracy}")
    if outcome.failures:
        sentences.append("Failed: " + "; ".join(outcome.failures))
    result = ". ".join(sentences) + "."
    date = today or time.strftime("%Y-%m-%d", time.gmtime())
    expectation = "The run ends `COMPLETE`, holdout accuracy as in T1; each task ran at its site's TES"
    cells = ["SDK run", nodes, date, expectation, result]
    return "| " + " | ".join(cell.replace("|", "/").replace("\n", " ") for cell in cells) + " |"


def check_secret_free(text: str, token: str, urls: Sequence[str]) -> None:
    """Make sure that a text has neither the token nor a host name of the run in it.

    Args:
        text: The text.
        token: The token.
        urls: URLs of the run, whose host names mustn't show.

    Raises:
        Stop: It has one of them, or any URL.
    """
    hosts = {urllib.parse.urlsplit(url).hostname for url in urls if url}
    folded = text.casefold()
    if token in text or "://" in text or any(host and host.casefold() in folded for host in hosts):
        raise Stop("the results row would hold the token or a host name: not writing it")


def summarize(outcome: Outcome) -> None:
    """Print what came out.

    Args:
        outcome: What the run came to.
    """
    print(f"\nrun ID: {outcome.run_id}")
    print(f"state: {outcome.state}  (NVFlare job: {outcome.job_status or '-'})")
    for task in outcome.tasks:
        line = f"  {task.site}: task {task.task_id} {task.state} at the WES"
        if task.gateway_state or task.backend or task.pinned is not None:
            pinned = {True: "yes", False: "NO", None: "-"}[task.pinned]
            line += f"; gateway: {task.gateway_state or '-'} at {task.backend or '-'}, pinned: {pinned}"
        if task.note:
            line += f" ({task.note})"
        print(line)
    print(f"holdout accuracy: {outcome.accuracy or '-'}")
    for failure in outcome.failures:
        print(f"[FAIL] {failure}")
    for hint in outcome.hints:
        print(f"  -> {hint}")


def run(args: argparse.Namespace, token: str, cli_path: pathlib.Path | None, work: pathlib.Path) -> Outcome:
    """Submit (or pick up) the run, follow it, and check what came out.

    Args:
        args: The options.
        token: The access token.
        cli_path: The CLI, or `None` to download it.
        work: A private temporary folder.

    Returns:
        What the run came to.

    Raises:
        Stop: Something before the run's end failed.
    """
    executable = cli_path or download_cli(work)
    home = work / "home"
    write_config(home, args.wes, args.gateway)
    cli = Cli(executable, home, token)
    print(f"[ok] {cli('--version')}")

    info = cli.json("service-info", "--service", "WES")
    if "NVFLARE" not in (info.get("workflow_type_versions") or {}):
        raise Stop(f"the WES doesn't offer NVFLARE: {info.get('workflow_type_versions')}")
    offered = [site for site in str((info.get("tags") or {}).get("sites", "")).split(",") if site]
    if offered and not set(args.sites) <= set(offered):
        raise Stop(f"the hub has the sites {offered}, not {args.sites}")
    print(f"[ok] the WES answers, offers NVFLARE and the sites {args.sites}")

    if args.run_id:
        outcome = Outcome(run_id=args.run_id, picked_up=True)
        print(f"following run {outcome.run_id}")
    else:
        outcome = Outcome(run_id=submit(cli, args.job, args.sites))
        print(f"run {outcome.run_id} submitted")
    follow(cli, outcome, args.timeout, args.interval)
    if outcome.state not in TERMINAL:
        # Still running, or its state unknown: nothing to check yet
        return outcome

    try:
        log = retried(lambda: cli.json("wes", "get", outcome.run_id), time.sleep)
    except Stop as error:
        outcome.failures.append(f"the run's log couldn't be read ({explain_refusal(str(error))})")
        outcome.hints.append(f"follow the run again later with --run-id {outcome.run_id}")
        return outcome
    run_log = log.get("run_log") or {}
    outcome.wes_times = (str(run_log.get("start_time") or ""), str(run_log.get("end_time") or ""))
    outcome.job_status = str((log.get("outputs") or {}).get("flare_job_status") or "")
    outcome.tasks = site_tasks(log)
    if outcome.state != "COMPLETE":
        outcome.failures.append(f"the run ended {outcome.state}")
        errors = run_log.get("system_logs") or []
        if errors:
            print(f"the run's error: {scrub(str(errors[-1]), token)}")
    # The sites the run was submitted with, which differ from --sites if it was picked up with other options
    sites = ((log.get("request") or {}).get("workflow_params") or {}).get("sites") or args.sites
    if sorted(task.site for task in outcome.tasks) != sorted(sites):
        outcome.failures.append(f"client tasks for {[task.site for task in outcome.tasks]}, not {sites}")
    for task in outcome.tasks:
        if task.state != "COMPLETE":
            outcome.failures.append(f"the task of {task.site} ended {task.state}")
        if args.gateway:
            check_pinning(cli, task)
            if task.pinned is False:
                outcome.failures.append(f"the task of {task.site} didn't run at the TES it was pinned to")

    if outcome.state == "COMPLETE":
        model = work / "global_model.npy"
        problem = fetch_model(args.outputs_url or outputs_base(args.wes), outcome.run_id, token, model)
        if problem:
            outcome.failures.append(f"the global model couldn't be fetched ({problem})")
            outcome.hints.append(
                f"forward the hub's port (8080) and run again with --run-id {outcome.run_id}"
                " --outputs-url http://localhost:8080"
            )
        else:
            passed, output = evaluate(model, args.data, args.expect)
            lines = [line for line in output.splitlines() if line.startswith("holdout accuracy:")]
            outcome.accuracy = lines[0].removeprefix("holdout accuracy:").strip() if lines else ""
            if not passed:
                outcome.failures.append(f"evaluation: {output.splitlines()[-1] if output else 'no output'}")
    return outcome


def main(argv: Sequence[str] | None = None) -> int:
    """Run the script.

    Args:
        argv: Arguments, without the program's name; `sys.argv` if `None`.

    Returns:
        The exit status.
    """
    args = parse_args(argv)
    token = ""
    try:
        token = read_token(args.token_stdin)
        left = token_seconds_left(token)
        if left is not None and left < MIN_TOKEN_SECONDS:
            raise Stop(f"the token expires in {max(left, 0)} s: get a fresh one")
        print("[ok] token read" + (f", expires in {left // 60} min" if left is not None else ""))
        with tempfile.TemporaryDirectory(prefix="sdk-run-") as tmp:
            work = pathlib.Path(tmp)
            work.chmod(0o700)
            outcome = run(args, token, args.cli, work)
        summarize(outcome)
        row = results_row(outcome, args.nodes, bool(args.gateway))
        check_secret_free(row, token, [args.wes, args.gateway, args.outputs_url])
        out = args.out or pathlib.Path(f"sdk-run-{outcome.run_id[:8]}.md")
        out.write_text(row + "\n")
        print(f"\nresults row for docs/outcomes/results.md (also in {out}):\n{row}")
    except Stop as error:
        print(f"STOP: {scrub(str(error), token)}", file=sys.stderr)
        return 1
    if outcome.failures:
        return 1
    print(f"[ok] run {outcome.run_id} COMPLETE, from the GA4GH SDK CLI")
    return 0


if __name__ == "__main__":
    sys.exit(main())

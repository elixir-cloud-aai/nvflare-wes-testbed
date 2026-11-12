"""Check a hub for real sites from outside, as a node or anyone on the internet sees it.

Usage:
    outside_check.py [--fl-port <port>] [--admin-port <port>] [--during-run] [--insecure]
                     [--timeout <seconds>] <hub name> <kits host>

Run it from a machine outside the hub's network that isn't in `WES_ALLOWED_IPS`.
The hub name is the name in the kits, without a port; the kits host serves
`/kits` and `/sites` over HTTPS. With Compose, both are `FL_SERVER_NAME`. It checks:

- `/kits` and `/sites` answer with the WES' own 404s: no such kit or token, but
  the way is open.
- The WES doesn't answer with 200 on either name.
- The FL port is open. It only listens during a run, so a closed one is a warning,
  unless `--during-run` says that a run is going on.
- The FLARE admin port is closed.
- Both names resolve, as an unknown name would pass the checks of closed ports.

It prints one line per check, and ends with 1 if any failed. Only the standard
library, so that it runs with any Python 3.12 or later, also outside the image.
"""

import argparse
import dataclasses
import http.client
import json
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

# Enough for the WES' error messages; nothing is read beyond that
MAX_BODY = 4096


@dataclasses.dataclass(frozen=True)
class Answer:
    """What a request got.

    Attributes:
        status: HTTP status, or None if nothing answered over HTTP.
        body: Start of the body, as text.
        error: Why nothing answered, if nothing did.
    """

    status: int | None
    body: str = ""
    error: str = ""


@dataclasses.dataclass(frozen=True)
class Result:
    """Outcome of one check.

    Attributes:
        outcome: `ok`, `warn` or `FAIL`.
        message: What was checked, and what came back.
    """

    outcome: str
    message: str


def tls_context(verify: bool) -> ssl.SSLContext:
    """Make the TLS context of requests.

    Args:
        verify: Whether to check the server's certificate and name.

    Returns:
        The context.
    """
    context = ssl.create_default_context()
    if not verify:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def read_body(response: http.client.HTTPResponse | urllib.error.HTTPError) -> str:
    """Read the start of a body, or nothing if that fails.

    Args:
        response: A response, or an error status with its body.

    Returns:
        The start of the body, as text.
    """
    try:
        return response.read(MAX_BODY).decode("utf-8", "replace")
    except (OSError, http.client.HTTPException):
        return ""


def request(url: str, *, method: str = "GET", verify: bool = True, timeout: float = 10) -> Answer:
    """Send a request without a body, straight to the server, and tell what came back.

    Proxies of the environment (`HTTPS_PROXY` and so on) aren't used: the checks
    are about what this machine reaches, and a proxy's refusal isn't the hub's.

    Args:
        url: URL to request.
        method: HTTP method.
        verify: Whether to check the server's certificate.
        timeout: Seconds to wait for the connection and each read.

    Returns:
        The status and the start of the body, or why there's none.
    """
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=tls_context(verify))
    )
    data = b"" if method == "POST" else None
    req = urllib.request.Request(url, data=data, method=method)
    try:
        with opener.open(req, timeout=timeout) as response:
            return Answer(response.status, read_body(response))
    except urllib.error.HTTPError as error:
        return Answer(error.code, read_body(error))
    except urllib.error.URLError as error:
        return Answer(None, error=str(error.reason))
    except (OSError, UnicodeError, http.client.HTTPException) as error:
        return Answer(None, error=str(error) or type(error).__name__)


def resolves(host: str) -> tuple[bool, str]:
    """Look up a name.

    Args:
        host: Host name or address.

    Returns:
        Whether it resolves, and why not if it doesn't.
    """
    try:
        socket.getaddrinfo(host, None)
    except (OSError, UnicodeError) as error:
        return False, str(error) or type(error).__name__
    return True, ""


def tcp_open(host: str, port: int, *, timeout: float = 5) -> tuple[bool, str]:
    """Try to open a TCP connection.

    Args:
        host: Host name or address.
        port: Port.
        timeout: Seconds to wait.

    Returns:
        Whether it opened, and why not if it didn't.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, ""
    except (OSError, UnicodeError) as error:
        return False, str(error) or type(error).__name__


def detail(answer: Answer) -> str | None:
    """Read FastAPI's `detail` from an error's body.

    Args:
        answer: What a request got.

    Returns:
        The detail, or None if the body has none.
    """
    try:
        body = json.loads(answer.body)
    except ValueError:
        return None
    return body.get("detail") if isinstance(body, dict) else None


def describe(answer: Answer) -> str:
    """Put what a request got in a few words.

    Args:
        answer: What a request got.

    Returns:
        Status and detail, or why nothing answered.
    """
    if answer.status is None:
        return f"no answer ({answer.error})"
    found = detail(answer)
    return f"{answer.status}" + (f" {found!r}" if found is not None else "")


def check_open_path(kits: str, path: str, method: str, expected: str, *, verify: bool, timeout: float) -> Result:
    """Check that a path reaches the WES, which has nothing for a made-up token.

    Args:
        kits: Kits host.
        path: Path with a made-up token.
        method: HTTP method.
        expected: The WES' `detail` with its 404.
        verify: Whether to check the certificate.
        timeout: Seconds to wait.

    Returns:
        ok if the WES' own 404 came back.
    """
    answer = request(f"https://{kits}{path}", method=method, verify=verify, timeout=timeout)
    ok = answer.status == 404 and detail(answer) == expected
    return Result(
        "ok" if ok else "FAIL",
        f"{method} https://{kits}{path}: {describe(answer)}, expected 404 {expected!r} from the WES",
    )


def check_no_wes(host: str, *, timeout: float) -> Result:
    """Check that the WES doesn't answer on a name.

    The certificate isn't checked, as anything that answers counts, whoever it
    claims to be.

    Args:
        host: Hub name or kits host.
        timeout: Seconds to wait.

    Returns:
        FAIL if the WES answered with 200.
    """
    url = f"https://{host}/ga4gh/wes/v1/service-info"
    answer = request(url, verify=False, timeout=timeout)
    return Result(
        "FAIL" if answer.status == 200 else "ok",
        f"GET {url}: {describe(answer)}, expected anything but 200",
    )


def check_fl_port(hub: str, port: int, *, during_run: bool, timeout: float) -> Result:
    """Check that the FL port is open.

    Args:
        hub: Hub name.
        port: FL port.
        during_run: Whether a run is going on, so the port must listen.
        timeout: Seconds to wait.

    Returns:
        ok if open; if closed, FAIL during a run, and a warning otherwise.
    """
    is_open, error = tcp_open(hub, port, timeout=timeout)
    if is_open:
        return Result("ok", f"FL port {hub}:{port}: open")
    if during_run:
        return Result("FAIL", f"FL port {hub}:{port}: closed ({error}), expected open during a run")
    return Result("warn", f"FL port {hub}:{port}: closed ({error}); it only listens during a run")


def check_admin_closed(hub: str, port: int, *, timeout: float) -> Result:
    """Check that the FLARE admin port is closed.

    Args:
        hub: Hub name.
        port: Admin port.
        timeout: Seconds to wait.

    Returns:
        FAIL if it's open.
    """
    is_open, error = tcp_open(hub, port, timeout=timeout)
    if is_open:
        return Result("FAIL", f"admin port {hub}:{port}: open, expected closed")
    return Result("ok", f"admin port {hub}:{port}: closed ({error})")


def check_resolves(host: str) -> Result:
    """Check that a name resolves, as an unknown one would pass the checks of closed ports.

    Args:
        host: Hub name, or kits host with an optional port.

    Returns:
        FAIL if it doesn't resolve.
    """
    name = urllib.parse.urlsplit(f"https://{host}").hostname or host
    found, error = resolves(name)
    return Result("ok" if found else "FAIL", f"name {name}: " + ("resolves" if found else f"doesn't resolve ({error})"))


def hub_name(value: str) -> str:
    """Read the hub's name from the command line.

    Args:
        value: The argument.

    Returns:
        The name.

    Raises:
        argparse.ArgumentTypeError: The name has a port.
    """
    if ":" in value:
        raise argparse.ArgumentTypeError(f"{value!r}: give the hub's name without a port, and the port with --fl-port")
    return value


def run_checks(args: argparse.Namespace) -> list[Result]:
    """Run all checks.

    Args:
        args: Parsed command line.

    Returns:
        One result per check.
    """
    verify = not args.insecure
    results = [check_resolves(host) for host in dict.fromkeys([args.kits, args.hub])]
    results += [
        check_open_path(
            args.kits, "/kits/no-such-token/site-1.tgz", "GET", "No such kit", verify=verify, timeout=args.timeout
        ),
        check_open_path(
            args.kits, "/sites/no-such-token/csr", "POST", "No such token", verify=verify, timeout=args.timeout
        ),
    ]
    for host in dict.fromkeys([args.kits, args.hub]):
        results.append(check_no_wes(host, timeout=args.timeout))
    results.append(check_fl_port(args.hub, args.fl_port, during_run=args.during_run, timeout=args.timeout))
    results.append(check_admin_closed(args.hub, args.admin_port, timeout=args.timeout))
    return results


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Read the command line.

    Args:
        argv: Arguments, without the program's name.

    Returns:
        The parsed arguments.
    """
    parser = argparse.ArgumentParser(description="Check a hub for real sites from outside.")
    parser.add_argument("hub", type=hub_name, help="name of the hub, as in the kits, without the port")
    parser.add_argument("kits", help="host that serves /kits and /sites over HTTPS, with :<port> if not 443")
    parser.add_argument("--fl-port", type=int, default=8002, help="FL port (default: %(default)s)")
    parser.add_argument("--admin-port", type=int, default=8003, help="FLARE admin port (default: %(default)s)")
    parser.add_argument("--during-run", action="store_true", help="a run is going on, so the FL port must be open")
    parser.add_argument(
        "--insecure", action="store_true", help="don't check certificates of /kits and /sites, e.g., of a test CA"
    )
    parser.add_argument("--timeout", type=float, default=10, help="seconds to wait per check (default: %(default)s)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the checks, print one line each, and tell whether all passed.

    Args:
        argv: Arguments, without the program's name; those of the process if None.

    Returns:
        0 if no check failed, 1 otherwise.
    """
    results = run_checks(parse_args(sys.argv[1:] if argv is None else argv))
    for result in results:
        print(f"[{result.outcome}] {result.message}")
    failed = sum(result.outcome == "FAIL" for result in results)
    print(f"{failed} of {len(results)} checks failed" if failed else f"all {len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

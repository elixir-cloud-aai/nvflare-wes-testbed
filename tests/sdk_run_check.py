"""`scripts/sdk_run.py` against the hub of `tests/hub.sh`, with the real GA4GH SDK CLI (#73).

The script downloads the CLI's release and checks its checksum, as for a user.
A caller whom the fake identity provider gives no entitlement (`outsider-*`)
must be refused with 403; a member's run must end `COMPLETE`, with the holdout
accuracy of T1, and a results row without the token or the hub's name.
"""

import os
import pathlib
import subprocess
import sys
import tempfile

from oidc_test_token import fetch

WES = os.environ["WES_URL"]
SCRIPT = "/app/scripts/sdk_run.py"
COMMON = ["--wes", WES, "--allow-http", "--token-stdin", "--data", "/testset-data", "--interval", "2"]
RESULTS: list[bool] = []


def check(name: str, passed: bool, detail: object = "") -> None:
    """Record a check and print it.

    Args:
        name: What is checked.
        passed: Whether it holds.
        detail: What to print along with it.
    """
    RESULTS.append(passed)
    print(f"[{'ok' if passed else 'FAIL'}] {name}: {detail}", flush=True)


def run_script(token: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the script with a token on standard input.

    Args:
        token: The access token.
        *args: More arguments.

    Returns:
        What it did.
    """
    return subprocess.run(  # an argument list, no shell
        [sys.executable, SCRIPT, *COMMON, *args],
        input=token + "\n",
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )


def main() -> None:
    """Run the script as a non-member, then as a member."""
    outsider = fetch("outsider-1")
    done = run_script(outsider)
    print(done.stdout + done.stderr, flush=True)
    check("a caller without the entitlement is refused", done.returncode == 1 and "403" in done.stderr, done.returncode)
    check("and told why", "not in the group the WES requires" in done.stderr)
    check("the token isn't printed", outsider not in done.stdout + done.stderr)

    member = fetch("researcher-1")
    with tempfile.TemporaryDirectory() as tmp:
        out = pathlib.Path(tmp) / "row.md"
        done = run_script(member, "--expect", "0.975", "--nodes", "site-1 and site-2, local", "--out", str(out))
        print(done.stdout + done.stderr, flush=True)
        row = out.read_text() if out.exists() else ""
    check("a member's run ends COMPLETE, with all checks", done.returncode == 0, done.returncode)
    check("the run's ID and state are printed", "run ID: " in done.stdout and "state: COMPLETE" in done.stdout)
    check(
        "each site's task is printed",
        all(f"{site}: task " in done.stdout for site in ("site-1", "site-2")),
    )
    check("the holdout accuracy is that of T1", "holdout accuracy: federated 0.975" in done.stdout)
    check("a results row is written", row.startswith("| SDK run | site-1 and site-2, local | "), row)
    host = WES.split("//", 1)[1].split(":", 1)[0].split("/", 1)[0]
    check("the row has neither the token nor the hub's name", bool(row) and member not in row and host not in row)
    check("the token isn't printed", member not in done.stdout + done.stderr)

    print(f"{sum(RESULTS)}/{len(RESULTS)} checks passed")
    sys.exit(0 if all(RESULTS) else 1)


if __name__ == "__main__":
    main()

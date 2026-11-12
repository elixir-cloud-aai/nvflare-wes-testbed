"""Check the WES's OIDC gate over real HTTP, through the fake identity provider (H5)."""

import os
import sys

import requests
from oidc_test_token import header


def main() -> None:
    """Hit a gated endpoint with no token and with a good one; check service-info stays open.

    Claim mismatches (wrong audience, issuer, signature, expiry) are already
    covered against a fake key, with no network, by `tests/auth_check.py`; this
    checks the real wiring instead: the `Authorization` header is read, and
    `/service-info` is reachable before any of that.
    """
    wes_url = os.environ["WES_URL"]
    runs = f"{wes_url}/runs"
    auth = header()

    checks = {
        "no token is rejected": requests.get(runs, timeout=30).status_code == 401,
        "a valid token is accepted": requests.get(runs, headers=auth, timeout=30).status_code == 200,
        "service-info stays reachable without a token": requests.get(f"{wes_url}/service-info", timeout=30).status_code
        == 200,
    }
    failed = 0
    for name, passed in checks.items():
        print(f"[{'ok' if passed else 'FAIL'}] {name}")
        failed += not passed
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

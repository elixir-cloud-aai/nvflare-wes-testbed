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
    `/service-info` is reachable before any of that. Also CORS over HTTP, for
    the origin of `WES_CORS_ORIGIN`, which the WES allows; the rest of CORS is
    in `tests/cors_check.py`.
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

    # Starting runs needs the entitlement that `compose.yaml` requires, which
    # the fake identity provider releases at userinfo only, as LS Login does
    # (#70): a member gets as far as the request, which names no workflow the
    # WES has (400); an outsider, in another group only, gets 403
    bad_run = {"workflow_type": "NONE", "workflow_type_version": "0", "workflow_url": "none"}
    member = requests.post(runs, headers=auth, data=bad_run, timeout=30)
    outsider = requests.post(runs, headers=header("outsider-1"), data=bad_run, timeout=30)
    checks["a member, by userinfo, gets as far as the request"] = member.status_code == 400
    checks["an outsider can't start runs"] = outsider.status_code == 403
    checks["an outsider still lists runs, none of them others'"] = (
        requests.get(runs, headers=header("outsider-1"), timeout=30).json().get("runs") == []
    )

    # CORS, over HTTP: a browser's preflight from the allowed origin, and a 401
    # its page can read
    origin = os.environ["WES_CORS_ORIGIN"]
    preflight = requests.options(
        runs,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization",
        },
        timeout=30,
    )
    refused = requests.get(runs, headers={"Origin": origin}, timeout=30)
    checks["a preflight from the allowed origin succeeds"] = (
        preflight.status_code == 200 and preflight.headers.get("Access-Control-Allow-Origin") == origin
    )
    checks["a 401 carries the allowed origin"] = (
        refused.status_code == 401 and refused.headers.get("Access-Control-Allow-Origin") == origin
    )
    failed = 0
    for name, passed in checks.items():
        print(f"[{'ok' if passed else 'FAIL'}] {name}")
        failed += not passed
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

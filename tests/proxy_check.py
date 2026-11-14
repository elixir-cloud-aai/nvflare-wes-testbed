"""Check what the reverse proxy of the hub lets through. Usage: proxy_check.py <name>."""

import os
import sys

import requests
import urllib3
from oidc_test_token import header

urllib3.disable_warnings()

# Only paths that reach the WES's own gate (H5) need it; the proxy's IP gate
# comes first for all of them, and a wrong path never reaches either gate
AUTH_PATHS = {"/ga4gh/wes/v1/runs", "/outputs/no-such-run/global_model.npy"}


def main() -> None:
    """Request each kind of path, and fail if any gives an unexpected status."""
    base = f"https://{sys.argv[1]}"
    wes = int(os.environ["WES_EXPECTED"])
    auth = header()
    expected = {
        # 404 comes from the WES behind the proxy: no such kit, but the way is open
        "/kits/no-such-token/site-1.tgz": 404,
        "/ga4gh/wes/v1/service-info": wes,
        "/ga4gh/wes/v1/runs": wes,
        "/outputs/no-such-run/global_model.npy": 404 if wes == 200 else wes,
        "/": 403,
        "/docs": 403,
        "/openapi.json": 403,
    }
    failed = 0
    for path, status in expected.items():
        # The proxy's certificate comes from its own test CA here (`tls internal`)
        got = requests.get(
            f"{base}{path}", headers=auth if path in AUTH_PATHS else {}, verify=False, timeout=30
        ).status_code  # nosemgrep
        print(f"[{'ok' if got == status else 'FAIL'}] {path}: {got}, expected {status}")
        failed += got != status
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

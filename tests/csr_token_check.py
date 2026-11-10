"""Check that a site's CSR slot signs once, and is dead on a second try."""

import asyncio
import os
import subprocess
import sys
import tempfile

from fastapi import HTTPException
from starlette.requests import Request


def make_request(body: bytes) -> Request:
    """Build a minimal ASGI request carrying a fixed body, for `sign_csr`.

    Args:
        body: The request body.

    Returns:
        The request.
    """

    async def receive() -> dict:
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({"type": "http"}, receive)


def main() -> None:
    """Sign one real certificate signing request, then replay it, and check the outcomes."""
    with tempfile.TemporaryDirectory() as base:
        os.environ["WES_WORKDIR"] = base
        sys.path.insert(0, "/app")
        from wes import app as wes

        run_id = "test-run"
        run_dir = wes.BASE / run_id
        run_dir.mkdir(parents=True)
        wes.init_ca(run_dir, "testproj")

        work = run_dir / "site-1-request"
        work.mkdir()
        (work / "participant.yaml").write_text(
            "name: testproj\n\nparticipants:\n  - name: site-1\n    type: client\n    org: testbed\n"
        )
        subprocess.run(
            ["nvflare", "cert", "request", "--participant", "participant.yaml"],
            cwd=work,
            check=True,
            capture_output=True,
            text=True,
        )
        csr = (work / "site-1" / "site-1.request.zip").read_bytes()

        token, _ = wes.issue_csr_token(run_id, "site-1")
        first = asyncio.run(wes.sign_csr(token, make_request(csr)))
        replay_status = None
        try:
            asyncio.run(wes.sign_csr(token, make_request(csr)))
        except HTTPException as error:
            replay_status = error.status_code

    checks = {
        "a fresh CSR slot signs the request": first.status_code == 200,
        "the same slot, replayed, is gone": replay_status == 404,
    }
    for name, passed in checks.items():
        print(f"[{'ok' if passed else 'FAIL'}] {name}")
    sys.exit(0 if all(checks.values()) else 1)


if __name__ == "__main__":
    main()

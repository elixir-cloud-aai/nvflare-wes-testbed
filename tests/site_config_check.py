"""Check how the thin WES reads its sites, and that tokens go only where they belong."""

import json
import os
import pathlib
import re
import sys
import tempfile
from typing import Any
from unittest import mock

import tokens_test

SITES = {
    "site-1": {"tes": "https://tes.site-1.example.org", "data": "https://example.org/1.csv", "token": "decoy-token-1"},
    "site-2": {"tes": "https://tes.site-2.example.org", "data": "https://example.org/2.csv"},
    "site-3": {"tes": "https://tes.site-3.example.org", "data": "https://example.org/3.csv", "token_file": ""},
}


class FakeResponse:
    """A response of a TES, with only a status."""

    def __init__(self, status_code: int) -> None:
        """Build the response.

        Args:
            status_code: Its status.
        """
        self.status_code = status_code


def main() -> None:
    """Load the WES with a sites file, and check its headers and task records."""
    # The mock provider of the unit tests, on this host
    with tempfile.TemporaryDirectory() as directory, tokens_test.provider() as provider:
        token_file = pathlib.Path(directory) / "site-3.token"
        token_file.write_text("decoy-file-token-1\n")
        sites = json.loads(json.dumps(SITES))
        sites["site-3"]["token_file"] = str(token_file)
        sites["site-4"] = {
            "tes": "https://tes.site-4.example.org",
            "data": "https://example.org/4.csv",
            "oauth": tokens_test.oauth(provider.issuer),
        }
        path = pathlib.Path(directory) / "sites.json"
        path.write_text(json.dumps(sites))
        os.environ["WES_SITES"] = '{"from-the-environment": {}}'
        os.environ["WES_SITES_FILE"] = str(path)
        os.environ["SITE_REFRESH_TOKEN"] = tokens_test.REFRESH_TOKEN
        sys.path.insert(0, "/app")
        from wes import app as wes

        secret_dropped = "SITE_REFRESH_TOKEN" not in os.environ
        url_4 = "https://tes.site-4.example.org/tasks"
        oauth_seen: list[str] = []

        def tes_4(method: str, url: str, headers: dict[str, str], **kwargs: Any) -> FakeResponse:
            oauth_seen.append(headers.get("Authorization", ""))
            return FakeResponse(200 if headers.get("Authorization") == "Bearer access-2" else 401)

        with mock.patch.object(wes.requests, "request", side_effect=tes_4):
            # A fresh token that the TES refuses isn't renewed: the refusal comes back, after one request
            fresh_status = wes.tes_request("POST", "site-4", url_4, timeout=1).status_code
            fresh_seen, fresh_grants = list(oauth_seen), len(provider.requests)
            oauth_seen.clear()
            # An older one is: the TES takes the next one
            with mock.patch.object(wes.tokens, "MIN_RENEW_INTERVAL", 0):
                oauth_status = wes.tes_request("POST", "site-4", url_4, timeout=1).status_code
                oauth_grants = [request["form"].get("grant_type") for request in provider.requests]
                renewed_seen = list(oauth_seen)
                # The provider fails just then: the refusal comes back, with no secret in the log
                provider.status = 503
                with (
                    mock.patch.object(wes.logger, "warning") as warning_retry,
                    mock.patch.object(wes.requests, "request", return_value=FakeResponse(401)),
                ):
                    failed_status = wes.tes_request("POST", "site-4", url_4, timeout=1).status_code
        logged_retry = json.dumps([str(call) for call in warning_retry.call_args_list])
        # The provider is still down: the cleanup goes on, and logs no secret
        run_4 = {"tasks": [{"site": "site-4", "id": "x", "base": "https://tes.site-4.example.org", "state": "RUNNING"}]}
        with mock.patch.object(wes.logger, "warning") as warning_4:
            wes.update_tasks(run_4)
            wes.cancel_tasks(run_4)
        logged_4 = json.dumps([str(call) for call in warning_4.call_args_list])

        # A TES out of reach must not break the cleanup of a run
        run = {"tasks": [{"site": "site-2", "id": "x", "base": "http://127.0.0.1:9", "state": "RUNNING"}]}
        wes.update_tasks(run)
        wes.cancel_tasks(run)
        refusals = {}
        for name, bad_sites in {
            "a bad token": {"site-1": {"tes": "https://tes", "token": "decoy-token-3\n"}},
            "a token over plain HTTP": {"site-1": {"tes": "http://tes", "token": "decoy-token-4"}},
            "a token file over plain HTTP": {"site-1": {"tes": "http://tes", "token_file": str(token_file)}},
            "two token sources": {"site-1": {"tes": "https://tes", "token": "decoy-5", "token_file": str(token_file)}},
            "a site named server": {"server": {"tes": "https://tes"}},
            "a refresh token shared by two sites": {
                site: {"tes": f"https://{site}", "oauth": tokens_test.oauth(provider.issuer)} for site in ("a", "b")
            },
            "a refresh token in two variables": {
                site: {
                    "tes": f"https://{site}",
                    "oauth": tokens_test.oauth(provider.issuer, refresh_token_env=variable),
                }
                for site, variable in (("a", "SITE_REFRESH_TOKEN"), ("b", "OTHER_REFRESH_TOKEN"))
            },
        }.items():
            try:
                same = {
                    "SITE_REFRESH_TOKEN": tokens_test.REFRESH_TOKEN,
                    "OTHER_REFRESH_TOKEN": tokens_test.REFRESH_TOKEN,
                }
                wes.load_sites(json.dumps(bad_sites), same)
                refusals[name] = "accepted"
            except ValueError as error:
                refusals[name] = str(error)
        wes.TES_GATEWAY = "https://gateway.example.org"
        gateway_headers = [wes.tes_headers("site-1"), wes.tes_headers("site-3")]
        wes.TES_GATEWAY = ""

        file_headers = [wes.tes_headers("site-3")]
        token_file.write_text("decoy-file-token-2")
        file_headers.append(wes.tes_headers("site-3"))

        # The TES of site 3 refuses the first token, which is renewed meanwhile;
        # the TES of site 1 refuses its one token
        seen: list[str] = []

        def tes(method: str, url: str, headers: dict[str, str], **kwargs: Any) -> FakeResponse:
            seen.append(headers.get("Authorization", ""))
            if "site-3" in url and len(seen) == 1:
                token_file.write_text("decoy-file-token-3")
                return FakeResponse(401)
            return FakeResponse(200 if headers.get("Authorization") == "Bearer decoy-file-token-3" else 401)

        with mock.patch.object(wes.requests, "request", side_effect=tes):
            renewed = wes.tes_request("GET", "site-3", "https://tes.site-3.example.org/x", timeout=1).status_code
            seen_renewal = list(seen)
            seen.clear()
            static = wes.tes_request("GET", "site-1", "https://tes.site-1.example.org/x", timeout=1).status_code
            seen_static = list(seen)

        # A token that can't be had leaves the cleanup of a run alone, and stays out of the logs
        token_file.unlink()
        run_3 = {"tasks": [{"site": "site-3", "id": "x", "base": "https://tes.site-3.example.org", "state": "RUNNING"}]}
        with mock.patch.object(wes.logger, "warning") as warning:
            wes.update_tasks(run_3)
            wes.cancel_tasks(run_3)
        logged = json.dumps([str(call) for call in warning.call_args_list])

    checks = {
        "a TES out of reach leaves the state of a task alone": run["tasks"][0]["state"] == "RUNNING",
        **{f"{name} is refused": refusal != "accepted" for name, refusal in refusals.items()},
        "the refusals don't hold the tokens": "decoy" not in json.dumps(refusals),
        "a shared refresh token is refused as such": all(
            "share a refresh token" in refusals[name]
            for name in ("a refresh token shared by two sites", "a refresh token in two variables")
        ),
        "the token of a site doesn't go to a gateway": gateway_headers == [{}, {}],
        "the file wins over the environment": set(wes.SITES) == {*SITES, "site-4"},
        "a site with a token gets it": wes.tes_headers("site-1") == {"Authorization": "Bearer decoy-token-1"},
        "a site without a token gets none": wes.tes_headers("site-2") == {},
        "no site, no token": wes.tes_headers("server") == {},
        "a token file is read for each request": file_headers
        == [{"Authorization": "Bearer decoy-file-token-1"}, {"Authorization": "Bearer decoy-file-token-2"}],
        "a refused token is renewed, and the request sent once more": renewed == 200
        and seen_renewal == ["Bearer decoy-file-token-2", "Bearer decoy-file-token-3"],
        "a refused token that can't be renewed is sent once": static == 401 and seen_static == ["Bearer decoy-token-1"],
        "a missing token leaves the task alone": run_3["tasks"][0]["state"] == "RUNNING" and warning.call_count == 2,
        "a missing token is logged without tokens": "site-3" in logged and "decoy" not in logged,
        "the task records hold no token": "decoy"
        not in json.dumps([wes.client_task("r", site, "proj", "https://k", "ab:cd") for site in ("site-1", "site-3")]),
        "the service info holds no token": "decoy" not in json.dumps(wes.service_info()),
        "the secrets of oauth sources don't go to child processes": secret_dropped,
        "a fresh oauth token that the TES refuses isn't renewed": fresh_status == 401
        and fresh_seen == ["Bearer access-1"]
        and fresh_grants == 1,
        "an older oauth token refused by the TES is renewed, and the request sent once more": oauth_status == 200
        and renewed_seen == ["Bearer access-1", "Bearer access-2"]
        and oauth_grants == ["refresh_token", "refresh_token"],
        "a refusal stands if the renewal fails": failed_status == 401
        and "site-4" in logged_retry
        and not re.search("decoy|access-", logged_retry),
        "a failing provider leaves the task alone": run_4["tasks"][0]["state"] == "RUNNING"
        and warning_4.call_count == 2,
        "a failing provider is logged without secrets": "site-4" in logged_4
        and not re.search("decoy|access-", logged_4),
    }
    for name, passed in checks.items():
        print(f"[{'ok' if passed else 'FAIL'}] {name}")
    sys.exit(0 if all(checks.values()) else 1)


if __name__ == "__main__":
    main()

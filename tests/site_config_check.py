"""Check how the thin WES reads its sites, and that tokens go only where they belong."""

import json
import os
import pathlib
import sys
import tempfile

SITES = {
    "site-1": {"tes": "https://tes.site-1.example.org", "data": "https://example.org/1.csv", "token": "decoy-token-1"},
    "site-2": {"tes": "https://tes.site-2.example.org", "data": "https://example.org/2.csv"},
}


def main() -> None:
    """Load the WES with a sites file, and check its headers and task records."""
    with tempfile.TemporaryDirectory() as directory:
        path = pathlib.Path(directory) / "sites.json"
        path.write_text(json.dumps(SITES))
        os.environ["WES_SITES"] = '{"from-the-environment": {}}'
        os.environ["WES_SITES_FILE"] = str(path)
        sys.path.insert(0, "/app")
        from wes import app as wes

    # A TES out of reach must not break the cleanup of a run
    run = {"tasks": [{"site": "site-2", "id": "x", "base": "http://127.0.0.1:9", "state": "RUNNING"}]}
    wes.update_tasks(run)
    wes.cancel_tasks(run)
    refusals = {}
    for name, sites in {
        "a bad token": {"site-1": {"tes": "https://tes", "token": "decoy-token-3\n"}},
        "a token over plain HTTP": {"site-1": {"tes": "http://tes", "token": "decoy-token-4"}},
        "a site named server": {"server": {"tes": "https://tes"}},
    }.items():
        try:
            wes.load_sites(json.dumps(sites))
            refusals[name] = "accepted"
        except ValueError as error:
            refusals[name] = str(error)
    wes.TES_GATEWAY = "https://gateway.example.org"
    gateway_headers = wes.tes_headers("site-1")
    wes.TES_GATEWAY = ""

    checks = {
        "a TES out of reach leaves the state of a task alone": run["tasks"][0]["state"] == "RUNNING",
        **{f"{name} is refused": refusal != "accepted" for name, refusal in refusals.items()},
        "the refusals don't hold the tokens": "decoy-token" not in json.dumps(refusals),
        "the token of a site doesn't go to a gateway": gateway_headers == {},
        "the file wins over the environment": set(wes.SITES) == set(SITES),
        "a site with a token gets it": wes.tes_headers("site-1") == {"Authorization": "Bearer decoy-token-1"},
        "a site without a token gets none": wes.tes_headers("site-2") == {},
        "no site, no token": wes.tes_headers("server") == {},
        "the task record holds no token": "decoy-token"
        not in json.dumps(wes.client_task("r", "site-1", "proj", "https://k", "ab:cd")),
        "the service info holds no token": "decoy-token" not in json.dumps(wes.service_info()),
    }
    for name, passed in checks.items():
        print(f"[{'ok' if passed else 'FAIL'}] {name}")
    sys.exit(0 if all(checks.values()) else 1)


if __name__ == "__main__":
    main()

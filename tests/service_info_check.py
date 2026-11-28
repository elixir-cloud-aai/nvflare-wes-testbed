"""Check the WES's service info: its defaults, the settings that override them, and its version (#71).

The Cloud Registry imports the service info and keeps syncing it, so its
values must be real: a reverse-domain `id`, the released version, the org's
current website, and description, documentation and contact. Imports the WES
in processes of their own, as it reads its settings on import, so it needs no
network. Runs in the image (`service-info-check` in
`tests/compose.hub-test.yaml`, which `tests/hub.sh` runs) or with the WES's
dependencies and the package installed (`pip install --no-deps .`):

    python3 tests/service_info_check.py

With `EXPECT_VERSION` set, the version must be that one, as CI checks it
against `pyproject.toml`, which isn't in the image.
"""

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import tomllib
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parent.parent
SETTINGS = (
    "WES_SERVICE_ID",
    "WES_SERVICE_NAME",
    "WES_SERVICE_DESCRIPTION",
    "WES_SERVICE_ENVIRONMENT",
    "WES_SERVICE_ORGANIZATION_NAME",
    "WES_SERVICE_ORGANIZATION_URL",
    "WES_SERVICE_CONTACT_URL",
    "WES_SERVICE_DOCUMENTATION_URL",
)
SCRIPT = "import json; from wes import app; print(json.dumps(app.service_info()))"


def service_info(environ: dict[str, str]) -> dict[str, Any]:
    """Import the WES in a process of its own, with settings, and get its service info.

    Args:
        environ: Settings for the service info; all others of `SETTINGS`, and
            `FL_SERVER_NAME`, are unset.

    Returns:
        The service info.

    Raises:
        RuntimeError: The WES didn't start, with its error output.
    """
    with tempfile.TemporaryDirectory() as base:
        env = {key: value for key, value in os.environ.items() if key not in (*SETTINGS, "FL_SERVER_NAME")}
        env.update({"WES_WORKDIR": base, "FL_PROBE_RESPONDER": "0", **environ})
        result = subprocess.run(
            [sys.executable, "-c", SCRIPT], cwd=ROOT, env=env, capture_output=True, text=True, check=False
        )
    if result.returncode:
        raise RuntimeError(result.stderr)
    info: dict[str, Any] = json.loads(result.stdout.splitlines()[-1])
    return info


def expected_version() -> str | None:
    """The version the service info must report, if known here.

    Returns:
        `EXPECT_VERSION`, or the version in `pyproject.toml` if this runs from
        a checkout, or None in the image without `EXPECT_VERSION`.
    """
    if os.environ.get("EXPECT_VERSION"):
        return os.environ["EXPECT_VERSION"]
    pyproject = ROOT / "pyproject.toml"
    if pyproject.is_file():
        version: str = tomllib.loads(pyproject.read_text())["project"]["version"]
        return version
    return None


def main() -> None:
    """Check the defaults, the overrides, empty settings and the version."""
    checks: dict[str, bool] = {}

    defaults = service_info({})
    checks["a reverse-domain id under the org's domain by default"] = (
        defaults["id"] == "cloud.elixir-on.nvflare-wes-testbed"
    )
    checks["the name by default"] = defaults["name"] == "Thin WES for NVFlare (sandbox)"
    checks["a description by default"] = "NVIDIA FLARE" in defaults.get("description", "")
    checks["a test service by default"] = defaults.get("environment") == "test"
    checks["the org by default, by its current name"] = defaults["organization"] == {
        "name": "ELIXIR On-Cloud",
        "url": "https://elixir-on.cloud/",
    }
    checks["the repo's issues as contact by default"] = (
        defaults.get("contactUrl") == "https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues"
    )
    checks["the docs of the public WES by default"] = defaults.get("documentationUrl") == (
        "https://nvflare-wes-testbed.readthedocs.io/en/latest/setup/real-sites/#the-wes-api-in-public"
    )
    checks["the WES API's type, unchanged"] = defaults["type"] == {
        "group": "org.ga4gh",
        "artifact": "wes",
        "version": "1.1.0",
    }

    want = expected_version()
    version = defaults["version"]
    checks["a version from the package, not the placeholder"] = version not in ("", "0.0.0", "unknown")
    if want is None:
        print("[skip] the version against pyproject.toml: set EXPECT_VERSION in the image")
    else:
        checks[f"the package's version ({want})"] = version == want

    overrides = {
        "WES_SERVICE_ID": "org.example.wes",
        "WES_SERVICE_NAME": "Example WES",
        "WES_SERVICE_DESCRIPTION": "A WES of the example org",
        "WES_SERVICE_ENVIRONMENT": "prod",
        "WES_SERVICE_ORGANIZATION_NAME": "Example org",
        "WES_SERVICE_ORGANIZATION_URL": "https://example.org/",
        "WES_SERVICE_CONTACT_URL": "mailto:wes@example.org",
        "WES_SERVICE_DOCUMENTATION_URL": "https://docs.example.org/wes",
        # Not a setting: the version is always the package's
        "WES_SERVICE_VERSION": "9.9.9",
        "SERVICE_VERSION": "9.9.9",
    }
    custom = service_info(overrides)
    checks["the id from WES_SERVICE_ID"] = custom["id"] == "org.example.wes"
    checks["the name from WES_SERVICE_NAME"] = custom["name"] == "Example WES"
    checks["the description from WES_SERVICE_DESCRIPTION"] = custom.get("description") == "A WES of the example org"
    checks["the environment from WES_SERVICE_ENVIRONMENT"] = custom.get("environment") == "prod"
    checks["the org from WES_SERVICE_ORGANIZATION_*"] = custom["organization"] == {
        "name": "Example org",
        "url": "https://example.org/",
    }
    checks["the contact from WES_SERVICE_CONTACT_URL"] = custom.get("contactUrl") == "mailto:wes@example.org"
    checks["the docs from WES_SERVICE_DOCUMENTATION_URL"] = (
        custom.get("documentationUrl") == "https://docs.example.org/wes"
    )
    checks["the version not settable"] = custom["version"] == version

    # As a chart or Compose file passes an unset value: the default, not an empty field
    empty = service_info(dict.fromkeys(SETTINGS, " "))
    checks["empty settings give the defaults"] = all(
        empty.get(key) == defaults.get(key)
        for key in ("id", "name", "description", "environment", "organization", "contactUrl", "documentationUrl")
    )
    named = service_info({"FL_SERVER_NAME": "flare-wes.example.org"})
    checks["the id from the hub's public name in reverse, if it has one"] = named["id"] == "org.example.flare-wes"
    dotted = service_info({"FL_SERVER_NAME": "flare-wes.example.org."})
    checks["the id without the trailing dot of a name"] = dotted["id"] == "org.example.flare-wes"
    ported = service_info({"FL_SERVER_NAME": "flare-wes.example.org:8443"})
    checks["the org's id, and no refusal, for a name that gives no valid id"] = ported["id"] == defaults["id"]
    single = service_info({"FL_SERVER_NAME": "fl-hub"})
    checks["the org's id for a name without a domain"] = single["id"] == defaults["id"]
    both = service_info({"FL_SERVER_NAME": "flare-wes.example.org", "WES_SERVICE_ID": "org.example.wes"})
    checks["WES_SERVICE_ID over the hub's name"] = both["id"] == "org.example.wes"
    spaced = service_info({"WES_SERVICE_ID": " org.example.wes "})
    checks["spaces around a setting dropped"] = spaced["id"] == "org.example.wes"

    # What registries would import as it is: the WES doesn't start, and names the setting
    for name, bad in (
        ("WES_SERVICE_ID", "org.example wes"),
        ("WES_SERVICE_ID", ".org.example"),
        ("WES_SERVICE_ENVIRONMENT", "test service"),
        ("WES_SERVICE_ORGANIZATION_URL", "http://example.org/"),
        ("WES_SERVICE_DOCUMENTATION_URL", "docs.example.org"),
        ("WES_SERVICE_CONTACT_URL", "wes@example.org"),
    ):
        try:
            service_info({name: bad})
            refused = ""
        except RuntimeError as error:
            refused = str(error)
        checks[f"refuses {name}={bad!r}"] = f"{name} isn't valid" in refused

    # Without the package's metadata, as from a checkout that isn't installed
    probe = subprocess.run(
        [sys.executable, "-c", "from wes import app; print(app.package_version('no-such-distribution-71'))"],
        cwd=ROOT,
        env={**os.environ, "FL_PROBE_RESPONDER": "0"},
        capture_output=True,
        text=True,
        check=False,
    )
    checks["'unknown' without the package's metadata"] = probe.stdout.strip() == "unknown"

    failed = 0
    for name, passed in checks.items():
        print(f"[{'ok' if passed else 'FAIL'}] {name}")
        failed += not passed
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

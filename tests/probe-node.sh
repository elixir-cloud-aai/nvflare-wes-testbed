#!/usr/bin/env bash
# The node probe against the local Funnel of site 1, whose tasks reach the hub and
# nothing else: where a node can take part, where it can't, and where it doesn't
# tell. Needs only Docker.
set -euo pipefail

# Runs the probe, and checks its exit code and the end of its output.
expect() {
    local code="$1" pattern="$2" output status=0
    shift 2
    output="$(docker compose --profile test run --rm -T probe-node python3 /app/tests/probe_submit.py \
        --tes=http://funnel-site-1:8000 --image=nvflare-testbed:local --ports=443 "$@" 2>/dev/null)" || status=$?
    echo "${output}"
    if [ "${status}" != "${code}" ] || ! grep -Eq "${pattern}" <<<"${output}"; then
        echo "[FAIL] expected exit code ${code} and '${pattern}', got ${status}"
        exit 1
    fi
}

expect 0 '^\[ok\] the node can take part' --hub=fl-hub --fl-port=8080
expect 1 "^\[FAIL\] the node can't take part: 1\.1\.1\.1:443 is (timeout|unreachable)" --hub=1.1.1.1 --fl-port=443
expect 2 '^\[inconclusive\] fl-hub:8002 refused' --hub=fl-hub --fl-port=8002
echo "[ok] the probe tells these cases apart"

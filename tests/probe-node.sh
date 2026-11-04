#!/usr/bin/env bash
# The node probe against the local Funnel of site 1, whose tasks reach the hub
# and nothing else: once where a node can take part, once where it can't.
# Needs only Docker.
set -euo pipefail

docker compose --profile test run --rm -T probe-node

if docker compose --profile test run --rm -T probe-node python3 /app/tests/probe_submit.py \
    --tes=http://funnel-site-1:8000 --hub=1.1.1.1 --ports=443 --image=nvflare-testbed:local; then
    echo "[FAIL] the probe must fail where no port is open"
    exit 1
fi
echo "[ok] the probe tells a node that can take part from one that can't"

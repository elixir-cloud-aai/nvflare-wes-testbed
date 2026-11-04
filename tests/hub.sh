#!/usr/bin/env bash
# The hub of `compose.hub.yaml`, without a machine: a run with local sites that
# dial the hub by its public name, then what its reverse proxy lets through, and
# what it must not hold. Needs only Docker, and the images of `compose.yaml`.
set -euo pipefail

export FL_SERVER_NAME=hub.testbed.invalid
export FL_IMAGE=nvflare-testbed:local
export HUB_TLS="tls internal"
export WES_SITES_FILE=tests/sites.hub-test.json
# Nodes here can't check the certificate of `tls internal`, so kits go over HTTP
export WES_INTERNAL_URL="http://${FL_SERVER_NAME}:8080"
hub=(docker compose -f compose.hub.yaml -f tests/compose.hub-test.yaml --project-directory .)
trap '"${hub[@]}" --profile test down -v' EXIT

config="$(docker compose -f compose.hub.yaml config)"
if grep -q 'docker.sock' <<<"${config}"; then
    echo "[FAIL] the hub must not get the Docker socket"
    exit 1
fi
if grep -Eq 'published: "?8003' <<<"${config}"; then
    echo "[FAIL] the FLARE admin port must stay inside"
    exit 1
fi
if grep -q 'funnel' <<<"${config}"; then
    echo "[FAIL] the hub must not bring a TES"
    exit 1
fi
echo "[ok] no Docker socket, admin port or TES in the hub's Compose file"

"${hub[@]}" --profile test run --rm -T site-config-check
"${hub[@]}" --profile test run --rm -T e2e
"${hub[@]}" up -d --wait proxy
"${hub[@]}" --profile test run --rm -T proxy-check

WES_ALLOWED_IPS=0.0.0.0/0 "${hub[@]}" up -d --wait --force-recreate proxy
WES_EXPECTED=200 "${hub[@]}" --profile test run --rm -T proxy-check
echo "[ok] the hub ran a job, and its proxy lets through what it should"

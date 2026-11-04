#!/bin/sh
# Run the FL server in the foreground, as the single executor of a TES task.
#
# Usage: fl-server <org> <kit.tgz>
set -eu
org="$1"
kit="$2"
workspace="$(mktemp -d /tmp/fl-server.XXXXXX)"
tar -xzf "$kit" -C "$workspace"
cd "$workspace"
timeout --kill-after=10s "${FL_SERVER_TIMEOUT:-1800}" \
    python3 -u -m nvflare.private.fed.app.server.server_train \
    -m "$workspace" -s fed_server.json \
    --set secure_train=true "org=$org" config_folder=config

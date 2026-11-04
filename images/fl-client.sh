#!/bin/sh
# Run an FL client in the foreground, as the single executor of a TES task.
#
# Usage: fl-client <site> <org> <kit.tgz>
#
# TES has no notion of a service: this script unpacks the startup kit into the
# task's scratch space, then blocks until the server shuts the client down. The
# timeout is the only guard against a server that never comes up: clients retry
# forever, and TES tasks have no time limit of their own.
set -eu
site="$1"
org="$2"
kit="$3"
workspace="$(mktemp -d /tmp/fl-client.XXXXXX)"
tar -xzf "$kit" -C "$workspace"
cd "$workspace"
timeout --kill-after=10s "${FL_CLIENT_TIMEOUT:-1800}" \
    python3 -u -m nvflare.private.fed.app.client.client_train \
    -m "$workspace" -s fed_client.json \
    --set secure_train=true "uid=$site" "org=$org" config_folder=config

#!/bin/sh
# Run an FL client in the foreground, as the single executor of a TES task.
#
# Usage: fl-client <site> <org> <project> <csr_url> <ca_fingerprint>
#
# The client makes its own key here, and sends out only a signing request
# (hack H4 correction): `csr_url` is the site's one slot at the WES, which signs it as
# the run's CA and hands back the certificate; `ca_fingerprint` lets the site
# check that CA out of band before trusting what it gets back. TES has no
# notion of a service: this script then blocks until the server shuts the
# client down. The timeout is the only guard against a server that never
# comes up: clients retry forever, and TES tasks have no time limit of their
# own.
set -eu
site="$1"
org="$2"
project="$3"
csr_url="$4"
fingerprint="$5"
workspace="$(mktemp -d /tmp/fl-client.XXXXXX)"
cd "$workspace"
cat > participant.yaml <<EOF
name: $project

participants:
  - name: $site
    type: client
    org: $org
EOF
nvflare cert request --participant participant.yaml
curl -sf -X POST "$csr_url" --data-binary "@$site/$site.request.zip" -o "$site/$site.signed.zip"
nvflare package "$site/$site.signed.zip" --fingerprint "$fingerprint"
cd "workspace/$project/prod_00/$site"
timeout --kill-after=10s "${FL_CLIENT_TIMEOUT:-1800}" \
    python3 -u -m nvflare.private.fed.app.client.client_train \
    -m . -s fed_client.json \
    --set secure_train=true "uid=$site" "org=$org" config_folder=config

#!/usr/bin/env bash
# The chart of the hub on Rahti (`charts/nvflare-wes-hub`), without a cluster:
# what it exposes, and what it refuses. Needs Helm and mikefarah's yq. With
# `KUBECONFORM` set to a kubeconform binary, it also checks the manifests
# against the schemas of OpenShift, which needs network.
set -euo pipefail

chart=charts/nvflare-wes-hub
# Placeholders only: `.invalid` names and an address for documentation (RFC 5737)
args=(
    --set image.tag=sha-0123456789abcdef0123456789abcdef01234567
    --set hubName=flare-wes.example.invalid
    --set kitsHost=flare-wes-kits.example.invalid
)
failed=0

ok() { echo "[ok] $1"; }
fail() {
    echo "[FAIL] $1"
    failed=1
}

# Each of these must fail to render
refuse() {
    local what="$1"
    shift
    if helm template hub "${chart}" "$@" >/dev/null 2>&1; then
        fail "renders ${what}"
    else
        ok "refuses ${what}"
    fi
}

refuse "without values"
refuse "without hubName" --set image.tag=sha-0123456789abcdef0123456789abcdef01234567 \
    --set kitsHost=flare-wes-kits.example.invalid
refuse "without kitsHost" --set image.tag=sha-0123456789abcdef0123456789abcdef01234567 \
    --set hubName=flare-wes.example.invalid
refuse "without an image tag" --set hubName=flare-wes.example.invalid \
    --set kitsHost=flare-wes-kits.example.invalid
refuse "a moving image tag" "${args[@]}" --set image.tag=dev
refuse "a hub name under rahtiapp.fi" "${args[@]}" --set hubName=flare-wes.2.rahtiapp.fi
refuse "an FL port below 30000" "${args[@]}" --set flPort=8002
refuse "an FL port above 35000" "${args[@]}" --set flPort=35001
refuse "the FLARE admin port as FL port" "${args[@]}" --set flPort=8003
refuse "a kits host with a scheme" "${args[@]}" --set kitsHost=https://flare-wes-kits.example.invalid
refuse "an address that isn't IPv4" "${args[@]}" --set loadBalancerIP=not-an-address

helm lint --strict "${chart}" "${args[@]}" >/dev/null && ok "lint" || fail "lint"

out="$(mktemp)"
trap 'rm -f "${out}"' EXIT
helm template hub "${chart}" "${args[@]}" --set flPort=30002 --set loadBalancerIP=192.0.2.10 >"${out}"

# Checks a yq expression on all rendered documents against an expected value
expect() {
    local what="$1" expr="$2" want="$3" got
    got="$(yq ea -r "${expr}" "${out}")"
    if [[ "${got}" == "${want}" ]]; then
        ok "${what}"
    else
        fail "${what}: got '${got}', expected '${want}'"
    fi
}

dep='select(.kind == "Deployment")'
ctr="${dep} | .spec.template.spec.containers[0]"
lb='select(.kind == "Service" and .spec.type == "LoadBalancer")'
route='select(.kind == "Route")'

expect "kinds" '[.kind] | sort | join(",")' "Deployment,Route,Service,Service"
expect "no Secret in the chart" '[select(.kind == "Secret")] | length' "0"
expect "one replica, replaced, not rolled" "${dep} | [.spec.replicas, .spec.strategy.type] | join(\" \")" "1 Recreate"
expect "the image at its tag" "${ctr} | .image" \
    "docker.io/elixircloud/nvflare-wes-testbed:sha-0123456789abcdef0123456789abcdef01234567"
expect "tasks get the same image" "${ctr} | .env[] | select(.name == \"FL_IMAGE\") | .value" \
    "docker.io/elixircloud/nvflare-wes-testbed:sha-0123456789abcdef0123456789abcdef01234567"
expect "HOME for an arbitrary user" "${ctr} | .env[] | select(.name == \"HOME\") | .value" "/tmp"
expect "no fixed user, as OpenShift picks one" \
    "[${dep} | .. | select(has(\"runAsUser\"))] | length" "0"
expect "the hub's name" "${ctr} | .env[] | select(.name == \"FL_SERVER_NAME\") | .value" \
    "flare-wes.example.invalid"
expect "kits by the Route's name, over https" \
    "${ctr} | .env[] | select(.name == \"WES_INTERNAL_URL\") | .value" \
    "https://flare-wes-kits.example.invalid"
expect "the FL port" "${ctr} | .env[] | select(.name == \"FL_PORT\") | .value" "30002"
expect "sites from the Secret's file" \
    "${ctr} | .env[] | select(.name == \"WES_SITES_FILE\") | .value" "/run/secrets/sites/sites.json"
expect "no sites in the environment" "[${ctr} | .env[] | select(.name == \"WES_SITES\")] | length" "0"
expect "the Secret, read-only" \
    "${dep} | .spec.template.spec.volumes[] | select(.name == \"sites\") | .secret.secretName" \
    "nvflare-wes-sites"
expect "the hub's name leads to the pod" \
    "${dep} | .spec.template.spec.hostAliases[0] | .ip + \" \" + (.hostnames | join(\",\"))" \
    "127.0.0.1 flare-wes.example.invalid"
expect "the container's ports" "[${ctr} | .ports[].containerPort] | join(\",\")" "8080,30002"
expect "no access log, as kit links are secrets" "${ctr} | .command | contains([\"--no-access-log\"])" "true"

expect "only the FL port on the address" "[${lb} | .spec.ports[] | .port] | join(\",\")" "30002"
expect "FL port goes to the FL port" "${lb} | .spec.ports[0].targetPort" "fl"
expect "no NodePorts" "${lb} | .spec.allocateLoadBalancerNodePorts" "false"
expect "the address asked for" "${lb} | .metadata.annotations[\"metallb.universe.tf/loadBalancerIPs\"]" \
    "192.0.2.10"
expect "only one Service with an address" \
    "[select(.kind == \"Service\" and .spec.type != \"ClusterIP\")] | length" "1"
expect "the FLARE admin port nowhere" \
    "[select(.kind == \"Service\") | .spec.ports[] | select(.port == 8003 or .targetPort == 8003)] | length" "0"

expect "Route only for /kits" "${route} | .spec.path" "/kits"
expect "Route at the kits host" "${route} | .spec.host" "flare-wes-kits.example.invalid"
expect "Route ends TLS at the router" "${route} | .spec.tls.termination" "edge"
expect "Route redirects plain HTTP" "${route} | .spec.tls.insecureEdgeTerminationPolicy" "Redirect"
expect "Route to the WES' Service" "${route} | .spec.to.name + \":\" + .spec.port.targetPort" \
    "hub-nvflare-wes-hub-wes:http"
expect "the WES' Service inside only" \
    "select(.kind == \"Service\" and .metadata.name == \"hub-nvflare-wes-hub-wes\") | .spec.type" "ClusterIP"
expect "one Route" '[select(.kind == "Route")] | length' "1"

# Without an address, MetalLB picks one of the project's
helm template hub "${chart}" "${args[@]}" >"${out}"
expect "no address asked for by default" "[${lb} | .metadata.annotations // {} | keys[]] | length" "0"
expect "FL port 30002 by default" "${lb} | .spec.ports[0].port" "30002"

# OpenShift 4.20's schemas, with its Route, at a fixed commit
schemas=https://raw.githubusercontent.com/melmorabity/openshift-json-schemas/62ad608b18edcd8ef4b6dd3741fc36115813fd18/v4.20-standalone-strict
if [[ -n "${KUBECONFORM:-}" ]]; then
    helm template hub "${chart}" "${args[@]}" | "${KUBECONFORM}" -strict -summary \
        -schema-location "${schemas}/{{.ResourceKind}}{{.KindSuffix}}.json" \
        && ok "schemas" || fail "schemas"
else
    echo "[skip] schemas: set KUBECONFORM to check them"
fi

exit "${failed}"

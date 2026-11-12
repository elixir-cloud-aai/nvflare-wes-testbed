#!/usr/bin/env bash
# The chart of the hub on Rahti (`charts/nvflare-wes-hub`), without a cluster:
# what it exposes, and what it refuses. Run it from the root of the
# repository. Needs Helm 3 and mikefarah's yq. With `KUBECONFORM` set to a
# kubeconform binary, it also checks the manifests against the schemas of
# OpenShift, which needs network:
#
#   KUBECONFORM=/path/to/kubeconform tests/chart.sh
set -euo pipefail

for tool in helm yq; do
    command -v "${tool}" >/dev/null || {
        echo "[FAIL] ${tool} is missing"
        exit 1
    }
done

chart=charts/nvflare-wes-hub
# Placeholders only: `.invalid` names, a name under Rahti's domain for the
# Route, and an address for documentation (RFC 5737)
tag=sha-0123456789abcdef0123456789abcdef01234567
image="docker.io/elixircloud/nvflare-wes-testbed:${tag}"
hub=flare-wes.example.invalid
kits=flare-wes-kits.example.rahtiapp.fi
wes=hub-nvflare-wes-hub-wes
tag_arg=(--set "image.tag=${tag}")
hub_arg=(--set "hubName=${hub}")
kits_arg=(--set "kitsHost=${kits}")
args=("${tag_arg[@]}" "${hub_arg[@]}" "${kits_arg[@]}")
failed=0

ok() { echo "[ok] $1"; }
fail() {
    echo "[FAIL] $1"
    failed=1
}

out="$(mktemp)"
trap 'rm -f "${out}"' EXIT

# Without this, every refusal below would pass on a broken chart or Helm
helm template hub "${chart}" "${args[@]}" >/dev/null || {
    echo "[FAIL] the chart doesn't render with valid values"
    exit 1
}

# Each of these must fail to render, by the schema
refuse() {
    local what="$1"
    shift
    if helm template hub "${chart}" "$@" >/dev/null 2>"${out}"; then
        fail "renders ${what}"
    elif grep -q "values don't meet the specifications of the schema" "${out}"; then
        ok "refuses ${what}"
    else
        fail "fails otherwise than by the schema ${what}: $(head -c 300 "${out}")"
    fi
}

refuse "without values"
refuse "without hubName" "${tag_arg[@]}" "${kits_arg[@]}"
refuse "without kitsHost" "${tag_arg[@]}" "${hub_arg[@]}"
refuse "without an image tag" "${hub_arg[@]}" "${kits_arg[@]}"
refuse "a moving image tag" "${args[@]}" --set image.tag=dev
refuse "a hub name under rahtiapp.fi" "${args[@]}" --set hubName=flare-wes.2.rahtiapp.fi
refuse "a hub name without a domain" "${args[@]}" --set hubName=flare-wes
refuse "an address as hub name" "${args[@]}" --set hubName=192.0.2.10
refuse "an FL port below 30000" "${args[@]}" --set flPort=8002
refuse "an FL port above 35000" "${args[@]}" --set flPort=35001
refuse "an unknown FL scheme" "${args[@]}" --set flScheme=https
refuse "a kits host with a scheme" "${args[@]}" --set kitsHost=https://${kits}
refuse "a kits host outside rahtiapp.fi, without a certificate" "${args[@]}" --set kitsHost=kits.example.invalid
refuse "the hub's name as kits host" "${args[@]}" --set "kitsHost=${hub}"
refuse "an address that isn't IPv4" "${args[@]}" --set loadBalancerIP=not-an-address
refuse "an address out of range" "${args[@]}" --set loadBalancerIP=256.0.0.1
refuse "an unknown value" "${args[@]}" --set flport=30003

helm lint --strict "${chart}" "${args[@]}" >/dev/null && ok "lint" || fail "lint"

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
env="${ctr} | .env[]"
lb='select(.kind == "Service" and .spec.type == "LoadBalancer")'
route='select(.kind == "Route")'
fullname="${wes%-wes}"
route_kits="select(.kind == \"Route\" and .metadata.name == \"${fullname}-kits\")"
route_csr="select(.kind == \"Route\" and .metadata.name == \"${fullname}-csr\")"

# Values other than the defaults, to see them arrive
helm template hub "${chart}" "${args[@]}" --set flPort=30123 --set flScheme=http \
    --set loadBalancerIP=192.0.2.10 --set sitesSecret=other-sites >"${out}"

expect "kinds" '[.kind] | sort | join(",")' "Deployment,Route,Route,Service,Service"
expect "no Secret in the chart" '[select(.kind == "Secret")] | length' "0"
expect "one replica, replaced, not rolled" "${dep} | [.spec.replicas, .spec.strategy.type] | join(\" \")" "1 Recreate"
expect "the image at its tag" "${ctr} | .image" "${image}"
expect "tasks get the same image" "${env} | select(.name == \"FL_IMAGE\") | .value" "${image}"
expect "HOME for an arbitrary user" "${env} | select(.name == \"HOME\") | .value" "/tmp"
expect "no fixed user, as OpenShift picks one" \
    "[${dep} | .. | select(tag == \"!!map\") | select(has(\"runAsUser\"))] | length" "0"
expect "the hub's name" "${env} | select(.name == \"FL_SERVER_NAME\") | .value" "${hub}"
expect "kits by the Route's name, over https" "${env} | select(.name == \"WES_INTERNAL_URL\") | .value" \
    "https://${kits}"
expect "the FL port" "${env} | select(.name == \"FL_PORT\") | .value" "30123"
expect "the FL scheme" "${env} | select(.name == \"FL_SCHEME\") | .value" "http"
expect "sites from the Secret's file" "${env} | select(.name == \"WES_SITES_FILE\") | .value" \
    "/run/secrets/sites/sites.json"
expect "no sites in the environment" "[${env} | select(.name == \"WES_SITES\")] | length" "0"
expect "the Secret, read-only" \
    "${dep} | .spec.template.spec | (.volumes[] | select(.name == \"sites\") | .secret.secretName) + \" \" + (.containers[0].volumeMounts[] | select(.name == \"sites\") | .readOnly)" \
    "other-sites true"
expect "the hub's name leads to the pod" \
    "${dep} | .spec.template.spec.hostAliases[0] | .ip + \" \" + (.hostnames | join(\",\"))" \
    "127.0.0.1 ${hub}"
expect "the container's ports" "[${ctr} | .ports[].containerPort] | join(\",\")" "8080,30123"
expect "no access log, as kit links are secrets" "${ctr} | .command | contains([\"--no-access-log\"])" "true"

expect "only the FL port on the address" "[${lb} | .spec.ports[] | .port] | join(\",\")" "30123"
expect "FL port goes to the FL port" "${lb} | .spec.ports[0].targetPort" "fl"
expect "no NodePorts" "${lb} | .spec.allocateLoadBalancerNodePorts" "false"
expect "the address asked for" "${lb} | .metadata.annotations[\"metallb.universe.tf/loadBalancerIPs\"]" \
    "192.0.2.10"
expect "only one Service with an address" \
    "[select(.kind == \"Service\" and .spec.type != \"ClusterIP\")] | length" "1"
expect "the FLARE admin port nowhere" \
    "[select(.kind == \"Service\") | .spec.ports[] | select(.port == 8003 or .targetPort == 8003)] | length" "0"

expect "two Routes, kits and csr" "[${route}] | length" "2"
expect "kits Route only for /kits" "${route_kits} | .spec.path" "/kits"
expect "kits Route at the kits host" "${route_kits} | .spec.host" "${kits}"
expect "kits Route ends TLS at the router" "${route_kits} | .spec.tls.termination" "edge"
expect "kits Route redirects plain HTTP" "${route_kits} | .spec.tls.insecureEdgeTerminationPolicy" "Redirect"
expect "kits Route to the WES' Service" "${route_kits} | .spec.to.name + \":\" + .spec.port.targetPort" "${wes}:http"
expect "csr Route only for /sites" "${route_csr} | .spec.path" "/sites"
expect "csr Route at the kits host" "${route_csr} | .spec.host" "${kits}"
expect "csr Route ends TLS at the router" "${route_csr} | .spec.tls.termination" "edge"
expect "csr Route redirects plain HTTP" "${route_csr} | .spec.tls.insecureEdgeTerminationPolicy" "Redirect"
expect "csr Route to the WES' Service" "${route_csr} | .spec.to.name + \":\" + .spec.port.targetPort" "${wes}:http"
expect "the WES' Service inside only" \
    "select(.kind == \"Service\" and .metadata.name == \"${wes}\") | .spec.type" "ClusterIP"

# Names stay within 63 characters, with the longest release name of Helm (53)
helm template "$(printf 'r%.0s' {1..53})" "${chart}" "${args[@]}" >"${out}"
expect "names within 63 characters, also with a long release name" \
    '[.metadata.name | select(length > 63)] | length' "0"

# The defaults. Without an address, MetalLB picks one of the project's
helm template hub "${chart}" "${args[@]}" >"${out}"
expect "no address asked for by default" "[${lb} | .metadata.annotations // {} | keys[]] | length" "0"
expect "FL port 30002 by default" "${lb} | .spec.ports[0].port" "30002"
expect "grpc by default" "${env} | select(.name == \"FL_SCHEME\") | .value" "grpc"
expect "the Secret's default name" \
    "${dep} | .spec.template.spec.volumes[] | select(.name == \"sites\") | .secret.secretName" "nvflare-wes-sites"
expect "not as root by default" "${dep} | .spec.template.spec.securityContext.runAsNonRoot" "true"
expect "the runtime's seccomp profile by default" \
    "${dep} | .spec.template.spec.securityContext.seccompProfile.type" "RuntimeDefault"
expect "no privilege escalation by default" "${ctr} | .securityContext.allowPrivilegeEscalation" "false"
expect "no capabilities by default" "${ctr} | .securityContext.capabilities.drop | join(\",\")" "ALL"

# Rahti's admission rejects RuntimeDefault, and sets a profile of its own when
# the pod names none: the override in the docs removes it and nothing else
helm template hub "${chart}" "${args[@]}" --set podSecurityContext.seccompProfile=null >"${out}"
expect "no seccomp profile with the override for Rahti" \
    "[${dep} | .. | select(tag == \"!!map\") | select(has(\"seccompProfile\"))] | length" "0"
expect "still not as root with the override for Rahti" \
    "${dep} | .spec.template.spec.securityContext.runAsNonRoot" "true"
expect "still no privilege escalation with the override for Rahti" \
    "${ctr} | .securityContext.allowPrivilegeEscalation" "false"

# OpenShift 4.20's schemas, with its Route, at a fixed commit
schemas=https://raw.githubusercontent.com/melmorabity/openshift-json-schemas/62ad608b18edcd8ef4b6dd3741fc36115813fd18/v4.20-standalone-strict
if [[ -n "${KUBECONFORM:-}" ]]; then
    helm template hub "${chart}" "${args[@]}" --set loadBalancerIP=192.0.2.10 | "${KUBECONFORM}" -strict -summary \
        -schema-location "${schemas}/{{.ResourceKind}}{{.KindSuffix}}.json" &&
        ok "schemas" || fail "schemas"
else
    echo "[skip] schemas: set KUBECONFORM to check them"
fi

exit "${failed}"

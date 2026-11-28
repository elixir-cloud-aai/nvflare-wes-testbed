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
issuer=https://login.example.invalid/oidc/
# The entitlement of the live deployment: no placeholder, as it's public
eoc='urn:geant:lifescience-ri.eu:group:elixir:ECP_CLN:EOC-Compute#aai.lifescience-ri.eu'
wes=hub-nvflare-wes-hub-wes
tag_arg=(--set "image.tag=${tag}")
hub_arg=(--set "hubName=${hub}")
kits_arg=(--set "kitsHost=${kits}")
oidc_arg=(--set "oidcIssuer=${issuer}")
args=("${tag_arg[@]}" "${hub_arg[@]}" "${kits_arg[@]}" "${oidc_arg[@]}")
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
refuse "without hubName" "${tag_arg[@]}" "${kits_arg[@]}" "${oidc_arg[@]}"
refuse "without kitsHost" "${tag_arg[@]}" "${hub_arg[@]}" "${oidc_arg[@]}"
refuse "without an image tag" "${hub_arg[@]}" "${kits_arg[@]}" "${oidc_arg[@]}"
refuse "without an oidcIssuer" "${tag_arg[@]}" "${hub_arg[@]}" "${kits_arg[@]}"
refuse "an oidcIssuer that isn't https" "${tag_arg[@]}" "${hub_arg[@]}" "${kits_arg[@]}" --set "oidcIssuer=http://login.example.invalid/oidc/"
refuse "a moving image tag" "${args[@]}" --set image.tag=dev
refuse "a hub name under rahtiapp.fi" "${args[@]}" --set hubName=flare-wes.2.rahtiapp.fi
refuse "a hub name without a domain" "${args[@]}" --set hubName=flare-wes
refuse "an address as hub name" "${args[@]}" --set hubName=192.0.2.10
refuse "an FL port below 30000" "${args[@]}" --set flPort=8002
refuse "an FL port above 35000" "${args[@]}" --set flPort=35001
refuse "an unknown FL scheme" "${args[@]}" --set flScheme=https
refuse "a probe responder that isn't on or off" "${args[@]}" --set-string probeResponder=yes
refuse "a kits host with a scheme" "${args[@]}" --set kitsHost=https://${kits}
refuse "a kits host outside rahtiapp.fi, without a certificate" "${args[@]}" --set kitsHost=kits.example.invalid
refuse "the hub's name as kits host" "${args[@]}" --set "kitsHost=${hub}"
refuse "an address that isn't IPv4" "${args[@]}" --set loadBalancerIP=not-an-address
refuse "an address out of range" "${args[@]}" --set loadBalancerIP=256.0.0.1
refuse "an unknown value" "${args[@]}" --set flport=30003
refuse "a token Secret that isn't a name" "${args[@]}" --set tokenSecret=Not_A_Name
refuse "an environment Secret that isn't a name" "${args[@]}" --set envSecret=Not_A_Name
refuse "a WES Route that isn't on or off" "${args[@]}" --set-string wesRoute.enabled=yes
refuse "an allow-list of empty entries, which the WES reads as none" "${args[@]}" --set 'oidcAllowedSubs=\,'
refuse "an allow-list of spaces" "${args[@]}" --set-string 'oidcAllowedSubs= '
refuse "an allow-list with spaces around entries" "${args[@]}" --set 'oidcAllowedSubs=researcher-1 \, researcher-2'
refuse "entitlements of empty entries, which the WES refuses" "${args[@]}" --set 'oidcRequiredEntitlements=\,'
refuse "entitlements with spaces around entries" "${args[@]}" \
    --set 'oidcRequiredEntitlements=urn:x:a#y \, urn:x:b#y'
refuse "an empty entitlement claim" "${args[@]}" --set-string oidcEntitlementClaim=
refuse "an entitlement claim with spaces" "${args[@]}" --set-string 'oidcEntitlementClaim=eduperson entitlement'
refuse "an open WES that isn't on or off" "${args[@]}" --set-string wesRoute.allowAnySubject=yes
refuse "an unknown key of the WES Route" "${args[@]}" --set wesRoute.path=/
refuse "a service id with spaces" "${args[@]}" --set 'serviceInfo.id=fi.rahtiapp.flare wes'
refuse "an organization URL that isn't https" "${args[@]}" --set serviceInfo.organization.url=http://example.invalid/
refuse "a documentation URL that isn't https" "${args[@]}" --set serviceInfo.documentationUrl=docs.example.invalid
refuse "a contact that is neither https nor mailto" "${args[@]}" --set serviceInfo.contactUrl=wes@example.invalid
refuse "a mailto contact without an address" "${args[@]}" --set serviceInfo.contactUrl=mailto:nobody
refuse "an organization URL without a host" "${args[@]}" --set serviceInfo.organization.url=https://
refuse "an environment with spaces" "${args[@]}" --set-string 'serviceInfo.environment=test service'
refuse "an unknown key of the service info" "${args[@]}" --set serviceInfo.version=1.0.0
refuse "any origin for CORS" "${args[@]}" --set 'corsAllowedOrigins=*'
refuse "an origin without a scheme" "${args[@]}" --set corsAllowedOrigins=portal.example.invalid
refuse "an origin with a path" "${args[@]}" --set corsAllowedOrigins=https://portal.example.invalid/app
refuse "origins separated otherwise than by commas" "${args[@]}" \
    --set 'corsAllowedOrigins=https://portal.example.invalid https://other.example.invalid'
refuse "a gateway that isn't https" "${args[@]}" --set tesGateway.url=http://protes.example.invalid \
    --set tokenSecret=tes-tokens --set tesGateway.tokenFile=gateway
refuse "a gateway token file that isn't a key" "${args[@]}" --set tesGateway.url=https://protes.example.invalid \
    --set tokenSecret=tes-tokens --set tesGateway.tokenFile=../gateway
refuse "a gateway token as a value" "${args[@]}" --set tesGateway.url=https://protes.example.invalid \
    --set tesGateway.token=decoy
refuse "a gateway client secret as a value" "${args[@]}" --set tesGateway.url=https://protes.example.invalid \
    --set envSecret=tes-oauth --set tesGateway.oauth.client_secret=decoy

# Each of these must fail to render, by the chart's own checks
refuse_render() {
    local what="$1" why="$2"
    shift 2
    if helm template hub "${chart}" "$@" >/dev/null 2>"${out}"; then
        fail "renders ${what}"
    elif grep -q "${why}" "${out}"; then
        ok "refuses ${what}"
    else
        fail "fails otherwise ${what}: $(head -c 300 "${out}")"
    fi
}
gateway_arg=(--set tesGateway.url=https://protes.example.invalid)
refuse_render "a gateway without a token" "needs tesGateway.tokenFile or tesGateway.oauth" \
    "${args[@]}" "${gateway_arg[@]}"
refuse_render "a gateway token file without tokenSecret" "which is empty" \
    "${args[@]}" "${gateway_arg[@]}" --set tesGateway.tokenFile=gateway
refuse_render "a gateway token without a gateway" "need tesGateway.url" "${args[@]}" \
    --set tokenSecret=tes-tokens --set tesGateway.tokenFile=gateway
refuse_render "a gateway oauth without envSecret" "from envSecret, which is empty" "${args[@]}" "${gateway_arg[@]}" \
    --set tesGateway.oauth.grant_type=refresh_token
refuse_render "a public WES open to anyone the issuer vouches for, unless said so" \
    "while oidcAllowedSubs and oidcRequiredEntitlements are empty" "${args[@]}" --set wesRoute.enabled=true
refuse_render "a gateway token file and oauth" "not both" "${args[@]}" "${gateway_arg[@]}" \
    --set tokenSecret=tes-tokens --set tesGateway.tokenFile=gateway --set tesGateway.oauth.grant_type=refresh_token

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
helm template hub "${chart}" "${args[@]}" --set flPort=30123 --set flScheme=http --set probeResponder=false \
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
expect "the OIDC issuer" "${env} | select(.name == \"WES_OIDC_ISSUER\") | .value" "${issuer}"
expect "the OIDC audience default" "${env} | select(.name == \"WES_OIDC_AUDIENCE\") | .value" "fl-wes"
expect "the OIDC algorithms default" "${env} | select(.name == \"WES_OIDC_ALGORITHMS\") | .value" "RS256"
expect "no allow-list by default" "[${env} | select(.name == \"WES_OIDC_ALLOWED_SUBS\")] | length" "0"
expect "kits by the Route's name, over https" "${env} | select(.name == \"WES_INTERNAL_URL\") | .value" \
    "https://${kits}"
expect "the FL port" "${env} | select(.name == \"FL_PORT\") | .value" "30123"
expect "the FL scheme" "${env} | select(.name == \"FL_SCHEME\") | .value" "http"
expect "the probe responder switched off" "${env} | select(.name == \"FL_PROBE_RESPONDER\") | .value" "0"
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

# The WES API in public, for portals and clients: one more Route, for
# `/ga4gh/wes/v1` alone, on the kits host. The WES checks tokens itself (H5)
route_wes="select(.kind == \"Route\" and .metadata.name == \"${wes}\")"
helm template hub "${chart}" "${args[@]}" --set wesRoute.enabled=true --set oidcAllowedSubs=researcher-1 \
    --set 'corsAllowedOrigins=https://portal.example.invalid\,http://localhost:3000' >"${out}"
expect "kinds with the WES Route" '[.kind] | sort | join(",")' "Deployment,Route,Route,Route,Service,Service"
expect "WES Route only for /ga4gh/wes/v1" "${route_wes} | .spec.path" "/ga4gh/wes/v1"
expect "WES Route at the kits host" "${route_wes} | .spec.host" "${kits}"
expect "WES Route ends TLS at the router" "${route_wes} | .spec.tls.termination" "edge"
expect "WES Route redirects plain HTTP" "${route_wes} | .spec.tls.insecureEdgeTerminationPolicy" "Redirect"
expect "WES Route to the WES' Service" "${route_wes} | .spec.to.name + \":\" + .spec.port.targetPort" "${wes}:http"
expect "the kits Route unchanged with the WES Route" "${route_kits} | .spec.path" "/kits"
expect "the origins for CORS" "${env} | select(.name == \"WES_CORS_ALLOWED_ORIGINS\") | .value" \
    "https://portal.example.invalid,http://localhost:3000"

# The WES API in public for the members of a group (#70), without an
# allow-list: the entitlement is enough for the guard against an open WES
helm template hub "${chart}" "${args[@]}" --set wesRoute.enabled=true \
    --set "oidcRequiredEntitlements=${eoc}" >"${out}"
expect "a public WES for the members of a group" "[${route_wes}] | length" "1"
expect "the entitlement" "${env} | select(.name == \"WES_OIDC_REQUIRED_ENTITLEMENTS\") | .value" \
    "${eoc}"
expect "the entitlement claim by default" "${env} | select(.name == \"WES_OIDC_ENTITLEMENT_CLAIM\") | .value" \
    "eduperson_entitlement"
expect "no allow-list with the entitlement alone" "[${env} | select(.name == \"WES_OIDC_ALLOWED_SUBS\")] | length" "0"

# Both, and another claim: both must hold in the WES
helm template hub "${chart}" "${args[@]}" --set wesRoute.enabled=true --set oidcAllowedSubs=researcher-1 \
    --set 'oidcRequiredEntitlements=urn:x:a#y\,urn:x:b#y' --set oidcEntitlementClaim=entitlements >"${out}"
expect "the allow-list with the entitlements" "${env} | select(.name == \"WES_OIDC_ALLOWED_SUBS\") | .value" "researcher-1"
expect "entitlements" "${env} | select(.name == \"WES_OIDC_REQUIRED_ENTITLEMENTS\") | .value" "urn:x:a#y,urn:x:b#y"
expect "another entitlement claim" "${env} | select(.name == \"WES_OIDC_ENTITLEMENT_CLAIM\") | .value" "entitlements"

# The service info of this deployment, for registries (#71): every value
# arrives, and the version stays the image's
info=https://docs.example.invalid/wes
helm template hub "${chart}" "${args[@]}" --set serviceInfo.id=invalid.example.wes \
    --set 'serviceInfo.name=Example WES' --set 'serviceInfo.description=A WES\, for tests' \
    --set serviceInfo.environment=prod --set 'serviceInfo.organization.name=Example org' \
    --set serviceInfo.organization.url=https://example.invalid/ \
    --set serviceInfo.contactUrl=mailto:wes@example.invalid --set "serviceInfo.documentationUrl=${info}" >"${out}"
expect "the service id" "${env} | select(.name == \"WES_SERVICE_ID\") | .value" "invalid.example.wes"
expect "the service name" "${env} | select(.name == \"WES_SERVICE_NAME\") | .value" "Example WES"
expect "the service description" "${env} | select(.name == \"WES_SERVICE_DESCRIPTION\") | .value" "A WES, for tests"
expect "the service environment" "${env} | select(.name == \"WES_SERVICE_ENVIRONMENT\") | .value" "prod"
expect "the organization's name" "${env} | select(.name == \"WES_SERVICE_ORGANIZATION_NAME\") | .value" \
    "Example org"
expect "the organization's URL" "${env} | select(.name == \"WES_SERVICE_ORGANIZATION_URL\") | .value" \
    "https://example.invalid/"
expect "the contact" "${env} | select(.name == \"WES_SERVICE_CONTACT_URL\") | .value" "mailto:wes@example.invalid"
expect "the documentation" "${env} | select(.name == \"WES_SERVICE_DOCUMENTATION_URL\") | .value" "${info}"
expect "no version from the chart" "[${env} | select(.name == \"WES_SERVICE_VERSION\")] | length" "0"

# Names stay within 63 characters, with the longest release name of Helm (53)
helm template "$(printf 'r%.0s' {1..53})" "${chart}" "${args[@]}" --set wesRoute.enabled=true \
    --set wesRoute.allowAnySubject=true >"${out}"
expect "a public WES open to any subject, when said so" "[${route}] | length" "3"
expect "names within 63 characters, also with a long release name" \
    '[.metadata.name | select(length > 63)] | length' "0"

# The defaults. Without an address, MetalLB picks one of the project's
helm template hub "${chart}" "${args[@]}" >"${out}"
expect "no address asked for by default" "[${lb} | .metadata.annotations // {} | keys[]] | length" "0"
expect "FL port 30002 by default" "${lb} | .spec.ports[0].port" "30002"
expect "grpc by default" "${env} | select(.name == \"FL_SCHEME\") | .value" "grpc"
expect "the probe responder on by default" "${env} | select(.name == \"FL_PROBE_RESPONDER\") | .value" "1"
expect "the Secret's default name" \
    "${dep} | .spec.template.spec.volumes[] | select(.name == \"sites\") | .secret.secretName" "nvflare-wes-sites"
expect "not as root by default" "${dep} | .spec.template.spec.securityContext.runAsNonRoot" "true"
expect "the runtime's seccomp profile by default" \
    "${dep} | .spec.template.spec.securityContext.seccompProfile.type" "RuntimeDefault"
expect "no privilege escalation by default" "${ctr} | .securityContext.allowPrivilegeEscalation" "false"
expect "no capabilities by default" "${ctr} | .securityContext.capabilities.drop | join(\",\")" "ALL"
expect "no token Secret by default" \
    "[${dep} | .spec.template.spec.volumes[] | select(.name == \"tes-tokens\")] | length" "0"
expect "no token mount by default" "[${ctr} | .volumeMounts[] | select(.name == \"tes-tokens\")] | length" "0"
expect "no environment from a Secret by default" "[${ctr} | .envFrom // [] | .[]] | length" "0"
expect "no gateway by default" "[${env} | select(.name | test(\"^TES_GATEWAY\"))] | length" "0"
expect "no WES Route by default" "[${route_wes}] | length" "0"
expect "no entitlement by default" "[${env} | select(.name == \"WES_OIDC_REQUIRED_ENTITLEMENTS\")] | length" "0"
expect "no entitlement claim without entitlements" \
    "[${env} | select(.name == \"WES_OIDC_ENTITLEMENT_CLAIM\")] | length" "0"
expect "no CORS by default" "[${env} | select(.name == \"WES_CORS_ALLOWED_ORIGINS\")] | length" "0"
# A service id of this deployment's own, from its public name, as GA4GH
# services name themselves (`fi.rahtiapp.poiesis`); the WES's defaults for the rest
expect "the service id from the kits host in reverse by default" \
    "${env} | select(.name == \"WES_SERVICE_ID\") | .value" "fi.rahtiapp.example.flare-wes-kits"
expect "the WES's own service info otherwise by default" \
    "[${env} | select(.name | test(\"^WES_SERVICE_\")) | .name] | join(\",\")" "WES_SERVICE_ID"
# A release from before `serviceInfo`, upgraded with `--reuse-values`, has none
for missing in serviceInfo serviceInfo.organization; do
    if helm template hub "${chart}" "${args[@]}" --set "${missing}=null" >"${out}" 2>&1; then
        expect "renders without ${missing}, as after --reuse-values" \
            "${env} | select(.name == \"WES_SERVICE_ID\") | .value" "fi.rahtiapp.example.flare-wes-kits"
    else
        fail "renders without ${missing}, as after --reuse-values: $(head -c 300 "${out}")"
    fi
done

# Non-default OIDC values, to see them arrive
helm template hub "${chart}" "${args[@]}" --set oidcAudience=other-aud --set 'oidcAlgorithms=RS256\,ES256' \
    --set 'oidcAllowedSubs=researcher-1\,researcher-2' >"${out}"
expect "the OIDC audience" "${env} | select(.name == \"WES_OIDC_AUDIENCE\") | .value" "other-aud"
expect "the OIDC algorithms" "${env} | select(.name == \"WES_OIDC_ALGORITHMS\") | .value" "RS256,ES256"
expect "the allow-list" "${env} | select(.name == \"WES_OIDC_ALLOWED_SUBS\") | .value" "researcher-1,researcher-2"

# Tokens that get renewed: files from a Secret, mounted as a whole (no
# `subPath`, no `items`), so that a renewed token reaches the pod; and the
# secrets of `oauth` sources as environment variables. Never as values
helm template hub "${chart}" "${args[@]}" --set tokenSecret=tes-tokens --set envSecret=tes-oauth >"${out}"
expect "token files from their Secret" \
    "${dep} | .spec.template.spec.volumes[] | select(.name == \"tes-tokens\") | .secret.secretName" "tes-tokens"
expect "all token files, so that renewals arrive" \
    "${dep} | .spec.template.spec.volumes[] | select(.name == \"tes-tokens\") | .secret | has(\"items\")" "false"
expect "token files read-only, by the pod's group" \
    "${dep} | .spec.template.spec.volumes[] | select(.name == \"tes-tokens\") | .secret.defaultMode" "0440"
expect "token files at their path, read-only, whole" \
    "${ctr} | .volumeMounts[] | select(.name == \"tes-tokens\") | .mountPath + \" \" + (.readOnly | tostring) + \" \" + (has(\"subPath\") | tostring)" \
    "/run/secrets/tes-tokens true false"
expect "the sites file still from its Secret" \
    "${ctr} | .volumeMounts[] | select(.name == \"sites\") | .mountPath" "/run/secrets/sites"
expect "environment from the Secret" "${ctr} | .envFrom[0].secretRef.name" "tes-oauth"
expect "no secret as a value of the chart" "[${env} | select(.name | test(\"TOKEN|SECRET\"))] | length" "0"

# A gateway, with its token from a file of the token Secret, or from `oauth`:
# the source names a file or variables, never a token
helm template hub "${chart}" "${args[@]}" "${gateway_arg[@]}" --set tokenSecret=tes-tokens \
    --set tesGateway.tokenFile=gateway >"${out}"
expect "the gateway" "${env} | select(.name == \"TES_GATEWAY_URL\") | .value" "https://protes.example.invalid"
expect "the gateway's token file" "${env} | select(.name == \"TES_GATEWAY_TOKEN_SOURCE\") | .value" \
    '{"token_file":"/run/secrets/tes-tokens/gateway"}'
helm template hub "${chart}" "${args[@]}" "${gateway_arg[@]}" --set envSecret=tes-oauth \
    --set tesGateway.oauth.issuer=https://login.example.invalid/oidc/ \
    --set tesGateway.oauth.grant_type=refresh_token \
    --set tesGateway.oauth.client_id=hub \
    --set tesGateway.oauth.refresh_token_env=GATEWAY_REFRESH_TOKEN >"${out}"
expect "the gateway's oauth source" \
    "${env} | select(.name == \"TES_GATEWAY_TOKEN_SOURCE\") | .value | from_json | .oauth.refresh_token_env" \
    "GATEWAY_REFRESH_TOKEN"

# Clusters with a LimitRange often allow a CPU limit of at most 5 times the
# request (`maxLimitRequestRatio`), and refuse pods above it. Every container
# of the defaults sets both, as such a LimitRange fills in a missing one
max_ratio=5
# Millicores of a CPU quantity, in whole numbers: `400m`, `2` or `0.5`. Other
# forms (such as `1e3` or `0.0005`) fail the check, rather than pass unchecked
millicores() {
    awk -v q="$1" 'BEGIN {
        if (q ~ /^[0-9]+m$/) { print substr(q, 1, length(q) - 1) + 0; exit }
        if (q ~ /^[0-9]+(\.[0-9]{1,3})?$/) {
            n = split(q, p, ".")
            print p[1] * 1000 + (n > 1 ? substr(p[2] "00", 1, 3) : 0)
            exit
        }
        exit 1
    }'
}
containers="$(yq ea -r "${dep} | .spec.template.spec | (.initContainers // []) + .containers | .[] |
    .name + \" \" + (.resources.requests.cpu // \"-\") + \" \" + (.resources.limits.cpu // \"-\")" "${out}")"
[[ -n "${containers}" ]] || fail "no containers in the defaults"
while read -r name request limit; do
    if ! req_m="$(millicores "${request}")" || ! lim_m="$(millicores "${limit}")" || ((req_m == 0)); then
        fail "CPU request and limit of ${name} by default: got '${request}' and '${limit}'"
    elif ((lim_m <= max_ratio * req_m)); then
        ok "CPU limit at most ${max_ratio} times the request of ${name} by default (${limit}/${request})"
    else
        fail "CPU limit more than ${max_ratio} times the request of ${name} by default (${limit}/${request})"
    fi
done <<<"${containers}"

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

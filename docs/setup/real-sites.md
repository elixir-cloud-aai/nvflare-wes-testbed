# Real sites

!!! warning "Tried on Rahti and over two Nodes"
    The hub has run on Rahti, with the chart. [T8](../tests/t8-real-sites.md) runs there ended `COMPLETE` on 2026-11-12, 2026-11-16 and 2026-11-19, with both sites on one TES in the same cluster as the hub ([What differed on Rahti](#what-differed-on-rahti)), and on 2026-11-24 over the TESK of the FI and CZ Nodes, with LS Login tokens ([Report](../outcomes/report.md)). Both TES are ours; the hub hasn't run with Compose on a VM. The rest is what we expect it to take: see the [issues](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues).

## What the hub needs

A public address, with these open: the FL port, straight through to the FL server, as its TLS is mutual, and HTTPS for the links to kits, which nodes fetch. It needs a stable name, set in `FL_SERVER_NAME`: the kits contain it. The WES itself checks every caller against a trusted OIDC issuer, such as LS Login, mandatory, with no local-only bypass ([H5](../testbed/shortcuts.md#h5)): set `WES_OIDC_ISSUER`, and `WES_OIDC_AUDIENCE` if it differs from the default `fl-wes`. Tokens need no `email` claim: without one, the FLARE admin of a run is named after the token's `sub` (see [H5](../testbed/shortcuts.md#h5)). Only some addresses may also reach `/ga4gh/wes/v1`, and `/kits` stays open for nodes.

See [Deploying the hub](#deploying-the-hub) for where it goes, and how.

## What each site needs

- A TES that the WES can call directly, with a token if needed, one per site in the sites file. Only for the [stretch goal](../testbed/index.md#goals): the TES is known to the proTES in use.
- A task may open connections to the hub's FL port and HTTPS, may pull the public image, and may write to `/tmp`.
- A way to fetch its share of the [test set](#the-test-set) from a public `https` URL.

## The test set

Sites fetch their share from raw files of this repository, at a fixed commit, so the data can't change under a run. These links are public on purpose, which only works because the data is synthetic and describes nobody: see [H13](../testbed/shortcuts.md#h13). **Public or synthetic data only: no clinical data and no data from Trusted Research Environments, ever.**

| Site | `data` in `WES_SITES` | SHA-256 |
|---|---|---|
| First site | [`site-1.csv`](https://raw.githubusercontent.com/elixir-cloud-aai/nvflare-wes-testbed/b473b4b2d3246d6b5f74c31e209268e0c093e062/testset/data/site-1.csv) | `c578295a4bd973bb98fa2def75cffd50313dd9c7ab6b34f6548124a70103c001` |
| Second site | [`site-2.csv`](https://raw.githubusercontent.com/elixir-cloud-aai/nvflare-wes-testbed/b473b4b2d3246d6b5f74c31e209268e0c093e062/testset/data/site-2.csv) | `e1ce32c53696909df438ce665fabe78f384b56ff4ce786d9ecb0101dc754ebca` |
| Third site | [`site-3.csv`](https://raw.githubusercontent.com/elixir-cloud-aai/nvflare-wes-testbed/a5196a93586c2a3757284c40534a6ef71a5f5fcf/testset/data/site-3.csv) | `4994bf229b20893fe7bde50a80543f41fbf4070f6d232cd7e3728f326c052df1` |
| Fourth site | [`site-4.csv`](https://raw.githubusercontent.com/elixir-cloud-aai/nvflare-wes-testbed/a5196a93586c2a3757284c40534a6ef71a5f5fcf/testset/data/site-4.csv) | `665cb549024bee591d1d1873f585801f37c0d9aa78b8560bb08035234076652f` |

The first two shares are at an older commit than the others, as they haven't changed since. The holdout set isn't for sites: it stays with whoever compares the models.

### Running with n sites

With n sites, give them the first n shares, in the order of the table, one each, and run the job for n sites (for one site, see [T8](../tests/t8-real-sites.md#steps)):

| Sites | `workflow_url` (`NVFLARE`) | Expected federated accuracy |
|---|---|---|
| 2 | `logreg-fedavg` | 0.975 |
| 3 | `logreg-fedavg-3` | 0.975 |
| 4 | `logreg-fedavg-4` | 1.000 |

Name the sites in `workflow_params`, for example `{"sites": ["site-1", "site-2", "site-3"]}`; without it, a run takes all sites of the sites file. The WES refuses an `NVFLARE` run that names a site twice, or whose number of sites differs from what the job takes (its `min_clients`), with `400`: with more sites, FedAvg of NVFlare 2.9 would ask a random subset of them each round, and with fewer, the job wouldn't start. A plain FedAvg run (`FEDAVG`, [T10](../tests/t10-fedavg.md)) takes any number of sites.

The shares cover different parts of the feature space: give each site a different one, or the [expected accuracies](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/blob/dev/testset/README.md) won't hold. `compose.public-data.yaml` runs [T2](../tests/t2-wes-to-tes.md) with the URLs of the first two, locally, in CI, and `compose.three-sites.yaml` runs T2 and T10 with three local sites, in CI.

## The image

Nodes pull the one image for all participants: [`elixircloud/nvflare-wes-testbed`](https://hub.docker.com/r/elixircloud/nvflare-wes-testbed). CI builds and pushes it on every push to `dev`, once the tests have passed on a build of its own, as `dev` and as `sha-<commit>`. For a run on real sites, use a release, `X.Y.Z`, which is scanned and signed ([Releasing](../about/index.md#releasing)), or `sha-<commit>`, as `dev` moves, and set it as `FL_IMAGE`. A fork that sets the repository variable `DOCKERHUB_ORG` uses that organization in place of `elixircloud`. Startup kits, keys and site data stay out of it through `.dockerignore`, which CI checks by file name, with decoys, on a local build. It's a sandbox image: only releases are scanned and signed, not `dev` or `sha-<commit>` ([H20](../testbed/shortcuts.md#h20)).

## Probing a node

The biggest risk of the plan is whether a task at a node may reach the hub. The probe task finds that out before anyone relies on it, and it decides whether [B1](../testbed/options.md#b1-server-beside-the-wes) works at that node at all. It runs the [image](#the-image), and reports through its log whether it can reach the hub's ports, whether an `https` input arrives, whether `env` is passed, who it runs as, and whether `/tmp` is writable. It handles only the public [test set](#the-test-set), and no keys.

A running [hub](#what-the-hub-needs) answers probes on its FL port itself: while no run is active, its probe responder accepts connections there and closes them, and during a run the FL server listens. So probe an idle hub at any time, without agreeing on one with its operator. The WES stops the responder before the FL server of a run starts, and starts it again when the run has ended; a run never waits for it. It's on by default: `FL_PROBE_RESPONDER` in [Compose](#running-it-with-compose), `probeResponder` in the [chart](#running-it-on-rahti). It answers on the FL port only, the one port the hub publishes for nodes: other ports of `--ports` still take a listener. With the FL server in a TES task (`compose.server-task.yaml`), the hub runs no responder, so its FL port refuses outside a run: use a listener.

Without a hub yet, or with the responder switched off, start a listener on the machine of the hub first, with the same ports:

```sh
docker run --rm -p 8002:8002 elixircloud/nvflare-wes-testbed:dev python3 /app/tests/probe.py listen 8002
```

Stop the listener before you start the hub: while it holds the FL port, the hub can't publish it, and `docker compose up` fails. A listener inside the hub's own container makes the WES refuse runs, with "The FL port … is in use" in the run's `system_logs`, and the responder waits until it's gone.

Then, on any machine with Docker that can reach the TES:

```sh
docker run --rm -e TES_TOKEN elixircloud/nvflare-wes-testbed:dev \
    python3 /app/tests/probe_submit.py --tes https://<tes> --hub <hub> --fl-port 8002 --ports 443
```

`--fl-port` is the port that decides. `--ports` lists others to try, for information, such as 443 or the port of a [hub on Rahti](#where-it-goes).

`TES_TOKEN` is taken from your environment, if the TES needs a token, and only goes over HTTPS. Through proTES, use its URL as `--tes`, and add `--backend https://<tes>` to pin the task to that TES. proTES 0.6.0 keeps the logs of the TES once a task has finished, so the script reads its findings from proTES. Only if they're missing does it ask that TES for the task, with the same token, which a TES refuses if it sees proTES's own client as the task's owner, as TESK does with [service tokens](#through-protes). If proTES keeps a final state that the TES didn't have, as it can when it polls a TESK just as a task ends ([protes#527](https://github.com/elixir-cloud-aai/protes/issues/527)), it keeps no logs, and the probe says `inconclusive`: run it again ([First run through proTES](../outcomes/report.md#first-run-through-protes)).

| Outcome for a port | Meaning |
|---|---|
| `open` | A task gets there |
| `refused` | Inconclusive: nothing listens (no hub, or its responder is off and no listener runs), or a firewall rejects the connection |
| `timeout` | Likely blocked by a firewall |
| `unreachable` | No route |
| `no-name` | The name doesn't resolve from the task |

| Last line | Exit code | Meaning |
|---|---|---|
| `[ok]` | 0 | The task completed and reached the FL port, and the input, `env` and `/tmp` work |
| `[FAIL]` | 1 | The node can't take part, as shown above that line |
| `[inconclusive]` | 2 | This doesn't tell: the FL port was `refused`, the log isn't in the task's record (the TES needn't keep it, so ask the operator), the task ran elsewhere than asked for, or it was canceled or still hadn't ended by `--timeout` |

The probe doesn't show that a node can fetch a startup kit from the hub, as its input comes from GitHub: a node with a strict allow-list may differ. That's what question 3 below is for. Record results per node in [Results](../outcomes/results.md), without hostnames. Besides local runs against Funnel, directly and through proTES ([Tests](../tests/index.md#local-runs)), it has run against a TESK in the hub's own cluster on Rahti: see [What differed on Rahti](#what-differed-on-rahti).

## What to ask node operators

1. May a TES task connect out to `<hub>:8002`, or `<hub>:443`? Through a proxy?
2. Are there limits on the run time of tasks? A run of the test set takes under a minute.
3. Does the TES need a token to submit tasks, and how does one get it? Which TES version and backend is it? Does it take `http(s)` inputs, and does it have a size limit for them? Does it pass `env` to executors?
4. Can it pull images from Docker Hub, and does it enforce non-root or read-only containers? (Either's fine.)
5. Who has access to task records and logs? They'd see the kit links ([H3](../testbed/shortcuts.md#h3)), for test federations only, which end with the run.

## Deploying the hub

!!! warning "Run on Rahti only"
    The chart has run on Rahti, on 2026-11-12, with a public address for the FL port, and a T8 run ended `COMPLETE`: see [What differed on Rahti](#what-differed-on-rahti). `tests/hub.sh` runs `compose.hub.yaml` in CI, with local sites that dial the hub by its name, as an arbitrary non-root user, and it checks what the proxy lets through; `tests/chart.sh` checks the chart without a cluster. Compose on a real machine, certificates from Let's Encrypt and anything on Nebius are untested: what's below about Nebius comes from its public docs, read on 2026-11-04.

### Where it goes

The plan is Rahti if it can expose the FL port, otherwise a VM with Nebius credits.

**Rahti can expose the FL port, on request, and only on a high port.** A Route is for HTTP, so the FL port takes a [`LoadBalancer` Service](https://docs.csc.fi/cloud/rahti/configurations/loadbalancer-service/), which isn't limited to HTTP or HTTPS:

| Way to expose it on Rahti | Works? | What it takes |
|---|---|---|
| `LoadBalancer` Service | Yes, by the docs | A request to the CSC Service Desk, with the Rahti project name, the `csc_project` number, a use case and the number of addresses. The port must be between 30000 and 35000 |
| `NodePort` | No | [NodePorts aren't enabled on Rahti](https://docs.csc.fi/cloud/rahti/configurations/loadbalancer-service/) |
| Passthrough Route on 443, by SNI | Perhaps, untried | [Passthrough leaves TLS to the pod](https://docs.csc.fi/cloud/rahti/usage/networking/), and [Red Hat names it as the way to client certificates](https://docs.redhat.com/en/documentation/openshift_container_platform/4.22/html/ingress_and_load_balancing/routes). Rahti's docs only describe Routes for HTTP. See below |

So on Rahti, `FL_PORT` is, for example, 30002, not 8002 or 443. **Whether tasks at a node may reach such a high port is the open question**, as sites more often allow 443. Tasks inside Rahti itself do, at the public address: see [What differed on Rahti](#what-differed-on-rahti). For other nodes, try it with the [probe](#probing-a-node), with `--fl-port 30002 --ports 8002,443`, and a listener on any machine with those ports open, before settling on Rahti.

What else differs on Rahti:

- Compose doesn't run there: it takes a Deployment, the `LoadBalancer` Service with `allocateLoadBalancerNodePorts: false`, and a Secret for the sites file. The Helm chart [`charts/nvflare-wes-hub`](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/tree/dev/charts/nvflare-wes-hub) has them: see [Running it on Rahti](#running-it-on-rahti).
- **Name:** the kits contain the name of the hub, and it must lead to the address of the `LoadBalancer`. Names under `rahtiapp.fi` should lead to the routers instead, so this takes a name of your own, with an `A` record.
- **Kits:** an edge Route with `path: /kits` exposes the links to kits, and nothing else of the WES. Reach the WES itself with `oc port-forward`, which needs no address list, or [make its API public](#the-wes-api-in-public) with a Route of its own for `/ga4gh/wes/v1`. To limit the FL port to the addresses of nodes, Rahti has a [NetworkPolicy](https://docs.csc.fi/cloud/rahti/configurations/loadbalancer-service/) with `externalTrafficPolicy: Local`. That takes the node selector `rahti.csc.fi/local-load-balancer: ''` on the pod, an address that no other Service shares, and a policy that still lets the router reach the `/kits` Route.
- **User:** pods run as an arbitrary user. The hub works that way, with `HOME=/tmp`: `tests/hub.sh` runs it so.
- **Name inside the pod:** the WES talks to its FL server by the name in the kits, so that name must lead to the pod itself, with `hostAliases`, as `extra_hosts` does in `compose.hub.yaml`.

A passthrough Route on 443 would be the way if nodes only let out 443, and there are three reasons not to count on it. NVFlare listens on the same port that its kits name, so the pod would have to bind to 443, which wasn't tried as an arbitrary user. The router tells connections apart by SNI: from the code of NVFlare 2.9, its clients connect by the name in their kit with nothing to override it, so they should send it, which wasn't observed. And the router may time out long-lived connections, which FLARE clients hold.

**Otherwise, a VM with Nebius credits.** There, the ports are free to choose, including 443 ([T7](../tests/t7-port-443.md)), and Compose runs as it is:

- Use a [static address, or an allocation](https://docs.nebius.com/compute/virtual-machines/network). A dynamic one may change, and the kits name the hub.
- By default, [all traffic is allowed](https://docs.nebius.com/vpc/security-groups/overview). Use a security group that only opens 80, 443 and the FL port, and SSH for yourself. An empty group blocks everything.

### Running it with Compose

On a machine with Docker, and a name that leads to it:

```sh
git clone https://github.com/elixir-cloud-aai/nvflare-wes-testbed.git
cd nvflare-wes-testbed
cp compose/sites.example.json sites.json    # edit it: never commit it
chmod 600 sites.json
export FL_SERVER_NAME=<name of the hub>
export FL_IMAGE=elixircloud/nvflare-wes-testbed:sha-<commit>
export WES_ALLOWED_IPS='<your address> <another>'
docker compose -f compose.hub.yaml up -d --wait
```

(In Fish: `set -x FL_SERVER_NAME <name of the hub>`, and so on.)

Caddy gets a certificate for that name, which needs ports 80 and 443 reachable. It only passes on `/kits`, which any node may fetch, and `/ga4gh/wes/v1` and `/outputs` from `WES_ALLOWED_IPS`; by default that's nobody from outside. Everything else gets a 403. That's an address list, not LS Login: see [H5](../testbed/shortcuts.md#h5) and [#5](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/5). Check on the machine that the proxy sees the real addresses of clients, as Docker's networking can hide them. The FLARE admin port stays inside. In this Compose file, the hub runs as root, which is what can read a `chmod 600` sites file. It has no access log, as links to kits are secrets while a run lasts. It keeps all state in memory, so a restart forgets runs ([H2](../testbed/shortcuts.md#h2)): check for tasks left at the sites after one.

| Variable | Default | Meaning |
|---|---|---|
| `FL_SERVER_NAME` | None, required | Public name of the hub, which goes into the kits |
| `FL_IMAGE` | `elixircloud/nvflare-wes-testbed:dev` | Image of the hub and the tasks. Use `sha-<commit>` |
| `FL_PORT`, `FL_SCHEME` | `8002`, `grpc` | FL port. For 443, use `http`: see [T7](../tests/t7-port-443.md) |
| `FL_PROBE_RESPONDER` | `1` | Answer [node probes](#probing-a-node) on the FL port while no run is active. `0` switches it off: then start a listener for a probe. Other values than `1`, `0`, `true`, `false`, `yes`, `no`, `on` and `off` stop the hub from starting |
| `FEDAVG_ROUND_TIMEOUT` | `300` | Seconds for all tasks of a round of a `FEDAVG` run ([C4](../testbed/options.md#c4-fedavg-as-a-plain-workflow)) to end; after that, the run fails and its tasks are canceled. A value that isn't a finite number, 0 or more, stops the hub from starting |
| `WES_ALLOWED_IPS` | `127.0.0.1` | Addresses or ranges that reach the WES, separated by spaces |
| `WES_OIDC_ISSUER` | None, required | Trusted OIDC issuer, e.g. LS Login's. `/runs*` and `/outputs` need a bearer token it issued; there's no way to start a run without one ([H5](../testbed/shortcuts.md#h5)) |
| `WES_OIDC_AUDIENCE` | `fl-wes` | The `aud` a token must carry, matching this deployment's registration at the issuer |
| `WES_OIDC_ALGORITHMS` | `RS256` | Signing algorithms accepted from the issuer, comma-separated |
| `WES_OIDC_ALLOWED_SUBS` | None, any caller | Subjects allowed to use the WES, comma-separated; a static allow-list, not real access control ([H22](../testbed/shortcuts.md#h22)) |
| `WES_OIDC_REQUIRED_ENTITLEMENTS` | None, no entitlement needed | Entitlements, one of which a caller needs to start runs, comma-separated, each matched exactly (no prefixes or wildcards): see [The WES API in public](#the-wes-api-in-public). From the token's `WES_OIDC_ENTITLEMENT_CLAIM`, or from the issuer's userinfo endpoint if the token has no such claim. Without one, `POST /runs` gets `403`; reading runs stays with their owner. With `WES_OIDC_ALLOWED_SUBS`, both must hold. A value of only commas or spaces stops the hub from starting |
| `WES_OIDC_ENTITLEMENT_CLAIM` | `eduperson_entitlement` | The claim that carries the entitlements. Empty, with `WES_OIDC_REQUIRED_ENTITLEMENTS` set, stops the hub from starting |
| `WES_CORS_ALLOWED_ORIGINS` | None | Origins whose pages may call the WES API from a browser (CORS), comma-separated, such as `https://portal.example.org`: see [The WES API in public](#the-wes-api-in-public). Only for `/ga4gh/wes/v1`; the proxy still lets the WES through from `WES_ALLOWED_IPS` alone. An entry that isn't an origin, such as `*`, stops the hub from starting |
| `WES_SERVICE_ID` | `FL_SERVER_NAME` in reverse and lower case, such as `org.example.flare-wes` for `flare-wes.example.org`; `cloud.elixir-on.nvflare-wes-testbed`, with a warning in the log, for a name without a dot, an address, or a name that doesn't give a valid id | The `id` in the [service info](#the-wes-api-in-public), for registries: one of the deployment's own, in reverse-domain notation. Set it once you register the hub, so that it stays if the name changes. Letters, digits, `.`, `_` and `-`, starting and ending with a letter or digit; another value stops the hub from starting |
| `WES_SERVICE_NAME` | `Thin WES for NVFlare (sandbox)` | The `name` in the service info |
| `WES_SERVICE_DESCRIPTION` | What the WES does, and that it's for tests only | The `description` in the service info |
| `WES_SERVICE_ENVIRONMENT` | `test` | The `environment` in the service info, such as `prod`, `test`, `dev` or `staging`: one word, or the hub doesn't start |
| `WES_SERVICE_ORGANIZATION_NAME`, `WES_SERVICE_ORGANIZATION_URL` | `ELIXIR On-Cloud`, `https://elixir-on.cloud/` | The `organization` in the service info: who runs the deployment. A URL that isn't https stops the hub from starting |
| `WES_SERVICE_CONTACT_URL` | `https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues` | The `contactUrl` in the service info: an https URL, or `mailto:` and an address; anything else stops the hub from starting |
| `WES_SERVICE_DOCUMENTATION_URL` | `https://nvflare-wes-testbed.readthedocs.io/en/latest/setup/real-sites/#the-wes-api-in-public` | The `documentationUrl` in the service info. A URL that isn't https stops the hub from starting |
| `WES_OIDC_ALLOW_HTTP` | None, https required | Local tests only: allows the issuer and its JWKS over plain HTTP. Never set it on a real deployment; an on-path attacker with it set could forge tokens |
| `WES_INTERNAL_URL` | `https://<FL_SERVER_NAME>` | Base of the links to kits. Keep it `https`, as kits hold private keys |
| `WES_SITES_FILE` | `./sites.json` | The sites file: name, `tes` and `data`. Add a [token source](#tokens-for-the-tes-of-the-sites) for a TES that needs one, which must then be at an `https` URL, and a `backend` for a site [through proTES](#through-protes) |
| `TES_GATEWAY_URL` | None, straight to each TES | A TES gateway (proTES) that all tasks go through, pinned to their site: see [Through proTES](#through-protes) |
| `TES_GATEWAY_TOKEN_SOURCE` | None | The gateway's token, as a JSON object with one [token source](#tokens-for-the-tes-of-the-sites) (`token`, `token_file` or `oauth`); needs `TES_GATEWAY_URL` at `https`. `TES_GATEWAY_TOKEN_URL` is for the local tests only ([T4](../tests/t4-protes.md)) |
| `HUB_HTTPS_PORT` | `443` | Another port for HTTPS, if the FL port is 443. Then set `WES_INTERNAL_URL` to match, and Let's Encrypt still needs port 80. The redirect from HTTP still points to 443, so use the `https` URL with its port |

Tokens in the sites file stay out of task records and logs, and the file stays out of Git and of the image. Tokens that expire during a run need a `token_file` or `oauth` source: see [Tokens for the TES of the sites](#tokens-for-the-tes-of-the-sites). To check the setup, run the [checks from outside](#checking-the-hub-from-outside) from a machine that isn't in `WES_ALLOWED_IPS`, with the name of the hub for both names, as `python3 tests/outside_check.py <hub> <hub>` (`<hub>:<HUB_HTTPS_PORT>` as the second with another port for HTTPS, and `--fl-port` with another FL port); then the [probe](#probing-a-node), then a run with one site ([T8](../tests/t8-real-sites.md)).

### Running it on Rahti

!!! note "Run on Rahti on 2026-11-12"
    The chart ran there as described below, and a T8 run ended `COMPLETE`. CI checks it with `helm lint`, OpenShift's schemas and `tests/chart.sh`, without a cluster. What differed from what we expected is in [What differed on Rahti](#what-differed-on-rahti).

The chart [`charts/nvflare-wes-hub`](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/tree/dev/charts/nvflare-wes-hub) holds the hub alone: the thin WES with its FL server, no proxy, no TES. It's a chart rather than plain manifests with Kustomize, as names, port and address are set with `--set`, so nothing about a deployment goes into a file of the repository, and its schema refuses what can't work on Rahti. It makes:

| Object | What it's for |
|---|---|
| Deployment | One pod, replaced, not rolled, on update. As OpenShift's arbitrary user, with `HOME=/tmp`. `hostAliases` lead the hub's name to the pod itself, as `extra_hosts` does in `compose.hub.yaml` |
| `LoadBalancer` Service `…-fl` | The FL port only, with `allocateLoadBalancerNodePorts: false` |
| `ClusterIP` Service `…-wes` | The WES, inside the cluster only |
| Route `…-kits` | `https://<kits name>/kits`, edge TLS, and no other path |
| Route `…-csr` | `https://<kits name>/sites`, where sites post the requests for their certificates, edge TLS |
| Route `…-wes` | Only with `wesRoute.enabled`: `https://<kits name>/ga4gh/wes/v1`, the WES API, edge TLS. See [The WES API in public](#the-wes-api-in-public) |

The sites file comes from a Secret that you create, which isn't part of the chart. By default, the WES API is not exposed at all: reach it with `oc port-forward`, which needs no address list (in place of `WES_ALLOWED_IPS` and [#5](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/5)), or make it public with `wesRoute.enabled`. The FLARE admin port stays inside the pod. Other pods of the same Rahti project could still reach the WES and the admin port at the pod's address, so keep the hub in a project of its own.

**Before you start:**

1. **An address from CSC.** Ask the [CSC Service Desk](https://docs.csc.fi/support/contact/), `servicedesk@csc.fi`, for one `LoadBalancer` address for your Rahti project, with the Rahti project name, the `csc_project` number, the use case (a federated learning hub for a BioHackathon sandbox, one TCP port between 30000 and 35000 for connections from compute sites) and the number of addresses: one. It can take some days.
2. **The probe.** Find out whether tasks at the nodes may reach a port that high: [probe them](#probing-a-node) with `--fl-port 30002 --ports 8002,443`. Before the hub runs, use a listener on any machine with those ports open:

    ```fish
    docker run --rm -p 30002:30002 -p 8002:8002 -p 443:443 elixircloud/nvflare-wes-testbed:sha-<commit> \
        python3 /app/tests/probe.py listen 30002 8002 443
    ```

    If the nodes only let out 443, Rahti won't do: use a VM, [as above](#where-it-goes).

    Once the hub runs, it answers probes on its FL port itself between runs (`probeResponder`, on by default): probe it with `--fl-port 30002`, and start no listener in its pod. With `--set probeResponder=false`, a listener in the hub's own pod holds the FL port while it runs, and the WES refuses runs, with "The FL port … is in use" in the run's `system_logs`. Start it with a terminal (`oc exec -it deploy/hub-nvflare-wes-hub -- python3 /app/tests/probe.py listen 30002`), and stop it with Ctrl-C before the first run. Without `-t`, it can stay behind after `oc` ends: then restart the pod, `oc rollout restart deployment/hub-nvflare-wes-hub`, which also forgets the hub's runs ([H2](../testbed/shortcuts.md#h2)).
3. **Two names.** The hub's name, of your own, for an `A` record to the address (not under `rahtiapp.fi`, which leads to the routers; the chart refuses it). And a name for the Route of the kits, which leads to the routers, so it can't be the same: a free name ending in `.rahtiapp.fi`, such as `<kits name>.2.rahtiapp.fi`, which works out of the box by [Rahti's docs](https://docs.csc.fi/cloud/rahti/usage/networking/), with the router's certificate. The chart has no certificate of its own, so it refuses other names.
4. **Tools:** `oc` and `helm` 3, logged in with the command that Rahti's web console copies for you (`oc login --token=…`, a secret: don't paste it anywhere else).

**Install it** (Fish), from a clone of this repository, with the [image](#the-image) at a `sha-` tag:

```fish
oc project <rahti project>
cp compose/sites.example.json sites.json    # edit it: never commit it
chmod 600 sites.json
oc create secret generic nvflare-wes-sites --from-file=sites.json=sites.json
helm install hub charts/nvflare-wes-hub \
    --set image.tag=sha-<commit> \
    --set hubName=<hub name> \
    --set kitsHost=<kits name> \
    --set oidcIssuer=<trusted OIDC issuer, https> \
    --set flPort=30002 \
    --set podSecurityContext.seccompProfile=null
oc rollout status deployment/hub-nvflare-wes-hub
oc get service hub-nvflare-wes-hub-fl -o jsonpath='{.status.loadBalancer.ingress[0].ip}'; echo
oc get ipaddresspools.metallb.io -n metallb-system <rahti project> -o jsonpath='{.metadata.annotations.ip_pairs}'; echo
oc get route hub-nvflare-wes-hub-kits -o jsonpath='{.status.ingress[0].conditions[0].type}={.status.ingress[0].conditions[0].status}'; echo
```

**Two addresses:** by the example in [Rahti's docs](https://docs.csc.fi/cloud/rahti/configurations/loadbalancer-service/), the project's pool holds internal addresses (`192.168.…`), and `ip_pairs` pairs each with a public one (`<internal> - <public>`), the one CSC tells you. The Service shows the internal one. **Point the `A` record of the hub's name to the public one**: the kits name it, and sites can't reach the internal one. With more than one address in the pool, pick one with `--set loadBalancerIP=<internal address>`, never the public one, which MetalLB can't assign. Without an address, the Service stays `<pending>`. Without the Secret, the pod waits in `ContainerCreating`.

**No seccomp profile of the chart's:** by default, the pod asks for the runtime's profile (`seccompProfile: type: RuntimeDefault`), which suits most clusters. Since 2026-11-10, Rahti's admission rejects pods that do, and sets a profile of its own on pods that name none: `--set podSecurityContext.seccompProfile=null` drops it, and leaves the rest of the security context as it is. In a values file, `podSecurityContext: {seccompProfile: null}` does the same. Without it, the ReplicaSet creates no pod, and `oc get events` names the profile.

The Route must say `Admitted=True`. If another project already has its name, the router rejects it (`HostAlreadyClaimed`), and links to kits would lead to someone else's app: pick another `kitsHost`, with `helm upgrade`.

**LimitRanges:** clusters with a LimitRange may cap the ratio of a container's limit to its request (`maxLimitRequestRatio`), often at 5 for CPU, and refuse pods above it. The defaults keep the CPU limit at 5 times the request (400m, up to 2), which `tests/chart.sh` checks. To change `resources`, set requests and limits together, such as `--set resources.requests.cpu=500m --set resources.limits.cpu=2`, and keep each ratio within your cluster's: `oc describe limitrange` shows it. Above it, the ReplicaSet creates no pod, and `oc get events` names the ratio.

| Value | Default | Meaning |
|---|---|---|
| `image.tag` | None, required | `sha-<commit>` of `dev`, for the hub and the tasks. `dev` is refused, as it moves |
| `hubName` | None, required | `FL_SERVER_NAME`: the hub's name in the kits, with an `A` record to the address |
| `kitsHost` | None, required | Name of the Route for `/kits`, without a scheme, ending in `.rahtiapp.fi`. Links to kits are `https://<kitsHost>/kits/…` |
| `flPort` | `30002` | FL port, on the address and in the pod: 30000 to 35000 |
| `flScheme` | `grpc` | `grpc`, or `http` (WebSocket, see [T7](../tests/t7-port-443.md)) |
| `probeResponder` | `true` | Answer [node probes](#probing-a-node) on the FL port while no run is active. `false` switches it off: then start a listener for a probe |
| `loadBalancerIP` | Empty | Internal address of the project's pool (`192.168.…`), not the public one. Empty: one of the pool's |
| `oidcIssuer` | None, required | Trusted OIDC issuer, https (e.g. LS Login's). The WES refuses every run and most endpoints without one ([H5](../testbed/shortcuts.md#h5)) |
| `oidcAudience` | `fl-wes` | The `aud` a token must carry, matching this deployment's registration at the issuer |
| `oidcAlgorithms` | `RS256` | Signing algorithms accepted from the issuer, comma-separated |
| `oidcAllowedSubs` | Empty, any caller | Subjects allowed to use the WES, comma-separated, without spaces or empty entries; a static allow-list, not real access control ([H22](../testbed/shortcuts.md#h22)) |
| `oidcRequiredEntitlements` | Empty, no entitlement needed | Entitlements, one of which a caller needs to start runs, comma-separated, without spaces or empty entries, each matched exactly, such as LS Login's `urn:geant:lifescience-ri.eu:group:elixir:ECP_CLN:EOC-Compute#aai.lifescience-ri.eu`: see [The WES API in public](#the-wes-api-in-public). `WES_OIDC_REQUIRED_ENTITLEMENTS` of the WES |
| `oidcEntitlementClaim` | `eduperson_entitlement` | The claim that carries the entitlements, in the token or at the issuer's userinfo endpoint. Only passed on with `oidcRequiredEntitlements` |
| `sitesSecret` | `nvflare-wes-sites` | Secret with the sites file under the key `sites.json` |
| `tokenSecret` | Empty | Secret with [token files](#tokens-for-the-tes-of-the-sites), one key per site, mounted whole at `/run/secrets/tes-tokens`, so that renewed tokens arrive without a restart. Empty: none |
| `envSecret` | Empty | Secret whose keys become environment variables of the hub: the secrets that [`oauth`](#tokens-for-the-tes-of-the-sites) sources name. Empty: none |
| `wesRoute.enabled` | `false` | A Route for the WES API, `/ga4gh/wes/v1` alone, on `kitsHost`: see [The WES API in public](#the-wes-api-in-public). Needs `oidcRequiredEntitlements`, `oidcAllowedSubs`, or `wesRoute.allowAnySubject` |
| `wesRoute.allowAnySubject` | `false` | `true` allows the Route with empty `oidcRequiredEntitlements` and `oidcAllowedSubs`: anyone the issuer vouches for may then start runs ([H22](../testbed/shortcuts.md#h22)) |
| `corsAllowedOrigins` | Empty, none | Origins whose pages may call the WES API from a browser (CORS), comma-separated, such as `https://portal.example.org`: scheme, host and an optional port, no path, no wildcard. `WES_CORS_ALLOWED_ORIGINS` of the WES |
| `serviceInfo.id` | Empty: `kitsHost` in reverse, such as `fi.rahtiapp.2.flare-wes`: the host of the WES's URL, not `hubName` as in Compose | `WES_SERVICE_ID`: the deployment's `id` in the [service info](#the-wes-api-in-public). Set it once you register the WES, so that it stays if `kitsHost` changes |
| `serviceInfo.name`, `serviceInfo.description`, `serviceInfo.environment` | Empty: the WES's defaults | `WES_SERVICE_NAME`, `WES_SERVICE_DESCRIPTION`, `WES_SERVICE_ENVIRONMENT` |
| `serviceInfo.organization.name`, `serviceInfo.organization.url` | Empty: the WES's defaults | `WES_SERVICE_ORGANIZATION_NAME`, `WES_SERVICE_ORGANIZATION_URL` (https) |
| `serviceInfo.contactUrl`, `serviceInfo.documentationUrl` | Empty: the WES's defaults | `WES_SERVICE_CONTACT_URL` (https or `mailto:`), `WES_SERVICE_DOCUMENTATION_URL` (https) |
| `tesGateway.url` | Empty, straight to each TES | A TES gateway (proTES), `https`, that all tasks go through: see [Through proTES](#through-protes) |
| `tesGateway.tokenFile` | Empty | The gateway's token: a key of `tokenSecret` with a token file. Or: |
| `tesGateway.oauth` | Empty | The gateway's token from an OAuth provider, with the keys of [`oauth`](#tokens-for-the-tes-of-the-sites) in the sites file (secrets by variable name only), and its secrets from `envSecret`, which it then needs. One of `tokenFile` and `oauth` is required with a gateway, and neither works without one; the chart takes no token or secret as a value |
| `podSecurityContext` | `runAsNonRoot: true`, `seccompProfile: {type: RuntimeDefault}` | Security context of the pod. On Rahti, `--set podSecurityContext.seccompProfile=null` |
| `securityContext` | `allowPrivilegeEscalation: false`, all capabilities dropped | Security context of the container |
| `resources` | 400m CPU and 1 GiB, up to 2 CPUs and 2 GiB | Requests and limits of the pod. The CPU limit stays at most 5 times the request (see LimitRanges above) |

**Reach the WES** (Fish), in a terminal of its own, which keeps the tunnel open:

```fish
oc port-forward service/hub-nvflare-wes-hub-wes 8080:8080
```

Then use `http://localhost:8080/ga4gh/wes/v1` in place of `https://<hub>/ga4gh/wes/v1`, for example in [T8](../tests/t8-real-sites.md). A run goes on in the pod if the tunnel drops.

#### The WES API in public

For a portal or a client elsewhere, such as a WES form in a browser or the GA4GH SDK's CLI, `wesRoute.enabled` adds a Route for `/ga4gh/wes/v1` alone, on the kits name: `https://<kits name>/ga4gh/wes/v1`. Nothing else of the WES gets routed: not `/outputs`, not FastAPI's `/docs` and `/openapi.json`. Rahti's router matches paths by whole segments, so `/ga4gh/wes/v1x` isn't routed either, and answers paths without a Route with its own 503, "Application is not available". The WES doesn't resolve `..` in paths, so `/ga4gh/wes/v1/../../docs` gets the WES' own 404. Every endpoint but `service-info` needs a bearer token of `oidcIssuer`, for `oidcAudience` ([H5](../testbed/shortcuts.md#h5)). There's no rate limiting ([H23](../testbed/shortcuts.md#h23)).

**Who may use it:** without a further check, anyone with an account at the issuer and a token for `oidcAudience` could start runs at the sites, and hold the one run slot ([H2](../testbed/shortcuts.md#h2), [H22](../testbed/shortcuts.md#h22)); with LS Login and a portal's client as audience, that's anyone who logs in to the portal. So the chart refuses `wesRoute.enabled` unless one of these says who may:

- `oidcRequiredEntitlements`: the members of a group. ELIXIR On-Cloud's compute services admit the members of EOC-Compute, `urn:geant:lifescience-ri.eu:group:elixir:ECP_CLN:EOC-Compute#aai.lifescience-ri.eu`, and so should this WES: access is then managed in one place, the group at LS Login, and not per deployment. Starting a run (`POST /runs`) needs one of the entitlements, matched exactly: the parent group `…:ECP_CLN#…` or a sibling such as `…:ECP_CLN:ADMIN#…` alone get `403`, and so does a subgroup of EOC-Compute, unless it is listed too. Reading runs, their status and logs stays with each run's owner, as before, also for callers without the entitlement.
- `oidcAllowedSubs`: a static list of subjects. With `oidcRequiredEntitlements` too, both must hold: a caller must be listed (for every endpoint) and have the entitlement (to start runs).
- `wesRoute.allowAnySubject=true`: open to anyone the issuer vouches for, on purpose.

Where the entitlements come from: the token's `oidcEntitlementClaim` (`eduperson_entitlement`) if it has that claim at all, even an empty one, and then userinfo isn't asked, as with Poiesis: at an issuer that puts the claim into tokens without the group, members get `403`, so check a decoded token too; otherwise the issuer's userinfo endpoint, from its discovery document, asked with the caller's token. LS Login releases `eduperson_entitlement` at userinfo only, not in access tokens, and only if the client asked for the scope `eduperson_entitlement`: a portal whose login doesn't ask for it gets `403` for every member. The WES keeps a userinfo answer per token, by its SHA-256, for 5 minutes at most and never beyond the token's expiry, so a member removed from the group can start runs for up to 5 more minutes with a token it already has. A userinfo endpoint that can't be reached, refuses the token, redirects, answers with more than 1 MiB or for longer than 10 seconds, or answers otherwise than with a JSON object about the token's `sub` is a `401`, never a pass, and isn't kept. The discovery document itself must answer `200`, without redirects, for the same issuer (trailing slash aside) and with a `jwks_uri`; otherwise the request fails (`503` for the token, `401` for userinfo) and the next request fetches it again. The WES logs subjects and what failed, never tokens or entitlements.

Check what the WES will see, with an access token of the portal's client (Fish):

```fish
curl -s -H "Authorization: Bearer $TOKEN" https://login.aai.lifescience-ri.eu/oidc/userinfo | jq .eduperson_entitlement
```

**What it shows and what it doesn't serve:** `service-info` needs no token, so it shows the names of the sites (`tags.sites`) to anyone. The global model of a `FEDAVG` run stays under `/outputs`, which isn't routed: a run log's `outputs.global_model` link doesn't work from outside. Fetch the model with `oc port-forward`, as above. The WES doesn't redirect a trailing slash (such as `/runs/`, a 404), as a redirect from behind the router would lead to `http://`.

A page in a browser that calls the WES from another origin needs CORS: name its origin in `corsAllowedOrigins`. The WES then answers preflights for `/ga4gh/wes/v1` from those origins, for `GET` and `POST` with the headers `Authorization` and `Content-Type`, without credentials (cookies), as bearer tokens need none. Other paths, such as `/kits`, never get CORS headers. Its token must carry the WES's audience: a portal registered with the issuer as a client of its own uses its client's ID as `oidcAudience`.

```fish
helm upgrade hub charts/nvflare-wes-hub --reset-then-reuse-values \
    --set wesRoute.enabled=true \
    --set 'oidcRequiredEntitlements=urn:geant:lifescience-ri.eu:group:elixir:ECP_CLN:EOC-Compute#aai.lifescience-ri.eu' \
    --set corsAllowedOrigins=https://<portal>
oc get route hub-nvflare-wes-hub-wes -o jsonpath='{.status.ingress[0].conditions[0].type}={.status.ingress[0].conditions[0].status}'; echo
curl -s https://<kits name>/ga4gh/wes/v1/service-info                    # 200
curl -s -o /dev/null -w '%{http_code}\n' https://<kits name>/ga4gh/wes/v1/runs   # 401
curl -s -o /dev/null -w '%{http_code}\n' -X OPTIONS https://<kits name>/ga4gh/wes/v1/runs \
    -H 'Origin: https://<portal>' -H 'Access-Control-Request-Method: POST' \
    -H 'Access-Control-Request-Headers: authorization'                 # 200
```

Or, for a list of subjects instead, `--set 'oidcAllowedSubs=<sub 1>\,<sub 2>'`. Several origins go with an escaped comma, as `--set 'corsAllowedOrigins=https://a.example.org\,https://b.example.org'`. Then run the [checks from outside](#checking-the-hub-from-outside) with `--wes-public`. To take the WES API off again, `--set wesRoute.enabled=false`.

**The service info, for registries:** `/ga4gh/wes/v1/service-info` describes the deployment, without a token, so that a GA4GH Service Registry, such as ELIXIR On-Cloud's Cloud Registry, can import it and keep it in sync: `id`, `name`, `description`, `organization`, `contactUrl`, `documentationUrl` and `environment` come from `serviceInfo` (`WES_SERVICE_*` of the WES, which Compose passes on too; the defaults are in the tables above), and `version` is the version of the package in the image, from `pyproject.toml` (an image of `dev` reports the version of the last release prepared there). The `id` names the deployment in the registry: give each deployment one of its own, and don't change it once it's registered. The chart takes the kits name in reverse by default; set `serviceInfo.id` to keep it if the kits name changes. For example (Fish):

```fish
helm upgrade hub charts/nvflare-wes-hub --reset-then-reuse-values \
    --set serviceInfo.id=<kits name in reverse, such as fi.rahtiapp.2.flare-wes> \
    --set 'serviceInfo.description=<what the deployment is for, and who may use it>'
curl -s https://<kits name>/ga4gh/wes/v1/service-info | jq '{id, version, organization, environment}'
```

Then register it by its URL, `https://<kits name>/ga4gh/wes/v1`. Like any update, changing these values restarts the pod, which forgets its runs ([H2](../testbed/shortcuts.md#h2)): change them between runs.

**Check from outside**, from a machine outside Rahti, with `flPort` as the FL port (see [Checking the hub from outside](#checking-the-hub-from-outside)):

```sh
python3 tests/outside_check.py --fl-port 30002 <hub name> <kits name>
```

Every check should say `[ok]`, also for the FL port outside a run, where the probe responder answers (a `[warn]` with `probeResponder=false`): `/kits` and `/sites` give the WES' own 404, the WES doesn't answer with 200 on either name, as the router has no Route for it and the address has only the FL port, and 8003 is closed. With `wesRoute.enabled`, add `--wes-public`: then the WES must answer `service-info` on the kits name, and refuse runs there without a token, with its own 401; it still mustn't answer on the hub's name. If the FL port times out during a run although the Service has its address, look for NetworkPolicies of the project (`oc get networkpolicy`) that keep it out: by Rahti's docs, pods only talk to pods of the same project by default.

**Acceptance:** a run with one site ([T8](../tests/t8-real-sites.md)) passes, `/kits` is reachable from outside, and the WES isn't.

**Update or remove it** (Fish). An update restarts the pod, which forgets its runs ([H2](../testbed/shortcuts.md#h2)): check for tasks left at the sites.

```fish
helm upgrade hub charts/nvflare-wes-hub --reset-then-reuse-values --set image.tag=sha-<commit>
helm uninstall hub
oc delete secret nvflare-wes-sites
```

`--reset-then-reuse-values` (Helm 3.14 or later) keeps your own values and takes up the chart's new defaults. `--reuse-values` would keep the defaults of the chart you installed: an install from before the CPU request of 400m would keep 250m.

After editing `sites.json`, replace the Secret and restart the pod:

```fish
oc create secret generic nvflare-wes-sites --from-file=sites.json=sites.json --dry-run=client -o yaml | oc replace -f -
oc rollout restart deployment/hub-nvflare-wes-hub
```

To limit the FL port to the addresses of nodes, Rahti has a [NetworkPolicy with `externalTrafficPolicy: Local`](https://docs.csc.fi/cloud/rahti/configurations/loadbalancer-service/). The chart doesn't do that yet.

#### What differed on Rahti

The first install on Rahti, on 2026-11-12, with sites on a TESK in the same cluster. These are notes for OpenShift in general, too: other clusters may set the same limits.

| What | What happened | What it takes now |
|---|---|---|
| LimitRange | The project's LimitRange allows a CPU limit of at most 5 times the request. The chart's old default, 250m up to 2 CPUs, is 8: the ReplicaSet created no pod, and the events named the ratio | Nothing: the default is 400m now ([#38](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/pull/38)). Check `oc describe limitrange` before you change `resources`: see LimitRanges above |
| Seccomp | Rahti's admission refuses pods that ask for `RuntimeDefault` | `--set podSecurityContext.seccompProfile=null`, as above |
| Address of the FL port | CSC gave one public address for the `LoadBalancer` Service, for ports between 30000 and 35000. The Service shows the internal address of the pair. From outside the cluster, the FL port answered at the public address | The `A` record of the hub's name leads to the public address, as above |
| What's public | The Routes expose `/kits` and `/sites` on the kits name, and nothing else of the WES. The WES API answered neither on the kits name nor on the hub's name, and the admin port was closed | Nothing: reach the WES with `oc port-forward` |
| Tasks in the same cluster | A TES task on Rahti reached the FL port at the public address: the probe said `open`, and the sites joined. Traffic from inside goes out and back in (hairpin) | Nothing. Nodes elsewhere still need the [probe](#probing-a-node) |
| Probe listener | A listener started in the hub's pod for the probe stayed behind and held the FL port. The FL server started without it, no site joined, and the first T8 ended in `SYSTEM_ERROR` after the start timeout | Runs fail at once now, with "The FL port … is in use" ([#41](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/pull/41)). The hub answers probes itself between runs now ([#46](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/46)), so it takes no listener. With `probeResponder=false`, start one only with `oc exec -it`, stop it with Ctrl-C, and restart the pod if one stayed behind |
| T8 | After a restart of the pod, the run over both sites, on the same TESK, ended `COMPLETE`, with the NVFlare job `FINISHED:COMPLETED`. Again on 2026-11-16, after a fresh restart of the pod, with the same outcome. The accuracies weren't checked | See [Results](../outcomes/results.md) |

The NetworkPolicies that Rahti puts in every project didn't keep the FL port or the Routes out. T8 ran within the 2 GiB memory limit.

### Tokens for the TES of the sites

!!! warning "Tested with a mock provider only"
    `tests/tokens_test.py` and `tests/site_config_check.py` check these sources against a mock token endpoint and a fake TES. They haven't run against a real identity provider yet.

Access tokens expire, often after an hour to a few hours. A run that lasts longer, or a hub that runs for days, needs a source that gets new ones. Each site of the sites file has at most one of these keys. Whichever it is, the token only goes to a TES at an `https` URL, never to a gateway (`TES_GATEWAY_URL`), and never into task records or logs.

| Key | What it holds | When the token is renewed |
|---|---|---|
| `token` | The token itself | Never. When it expires, the TES answers `401`: write a new sites file, and restart the hub between runs |
| `token_file` | The absolute path of a file with only the token, without surrounding white space | The file is read before each request to the TES, so whatever writes a new token into it (an updated Secret, a script) needs no restart. It must exist, with a token, when the hub starts: the hub doesn't start otherwise |
| `oauth` | Where and how to get tokens from an OAuth 2.0 provider | Tokens are cached, and renewed 60 seconds before they expire (at half their lifetime if that's shorter; after 5 minutes if the provider doesn't say, and after a day at the latest). If a renewal fails, the hub keeps using the old token while it's valid, and asks the provider again after 10 seconds. These times are fixed |

With `token_file` and `oauth`, a request that the TES answers with `401` is sent once more, but only with a token other than the refused one: for `token_file`, if the file holds a new one by then; for `oauth`, if the refused token is at least 30 seconds old, so that a TES that refuses every token doesn't make each request a renewal. If that renewal fails, the `401` stands. An `oauth` site looks like this:

```json
"site-1": {
  "tes": "https://tes.site-1.example.org",
  "data": "https://…/site-1.csv",
  "oauth": {
    "issuer": "https://login.example.org/oidc/",
    "grant_type": "refresh_token",
    "client_id": "<client ID>",
    "refresh_token_env": "SITE_1_REFRESH_TOKEN",
    "scope": "openid offline_access"
  }
}
```

| Key of `oauth` | Meaning |
|---|---|
| `issuer` | The provider's issuer: the token endpoint comes from its OpenID Connect discovery (`<issuer>/.well-known/openid-configuration`), which must name the same issuer. Or, instead: |
| `token_endpoint` | The token endpoint itself, for a provider without discovery |
| `grant_type` | `refresh_token` or `client_credentials` |
| `client_id` | The client's ID, which isn't a secret |
| `client_secret_env` | Name of the environment variable with the client secret: required for `client_credentials`, optional for `refresh_token` (without it, the client counts as public) |
| `refresh_token_env` | Name of the environment variable with the refresh token: required for `refresh_token` |
| `scope` | Optional: the scopes to ask for, separated by spaces |

**Which grant:** with `refresh_token`, tokens are those of the user whose refresh token it is, so the TES authorizes the tasks as that user, for example by the user's groups. Get the refresh token once, with the `offline_access` scope, for example through the device authorization grant of a client that allows it. With `client_credentials`, tokens are the client's own: only for a TES that accepts tokens of that client. Each site needs a refresh token of its own, in a variable of its own: many providers rotate refresh tokens on use, so a shared one would be spent by one site and refused for the other, and the hub doesn't start with the same refresh token in two sites, by one variable or two.

**Secrets** come in only when the hub starts, as environment variables, which the sites file names: never their values in the sites file, the image, a command line or a log. Once the hub has read them, it drops them from its environment, so that they aren't passed on to its child processes (`nvflare`, the FL server). Those run as the same user, though, so they could still read the hub's initial environment, and the token files: this is no isolation between them. Messages name sites and variables, never values. With a secret, the client authenticates with HTTP Basic (`client_secret_basic`). The hub follows no redirects of the provider, and takes `http` only for addresses of its own host, for tests. If the provider sends a new refresh token, the hub keeps it in memory: after a restart, it starts again from the one in the environment, which the provider may have revoked by then. Then get a new one.

**With Compose,** add an override file, say `compose.tokens.yaml`, which mounts the token files and passes on the variables from the shell that runs `docker compose`, without writing their values to a file:

```yaml
services:
  hub:
    volumes:
      - ./tes-tokens:/run/secrets/tes-tokens:ro
    environment:
      - SITE_1_REFRESH_TOKEN
```

```sh
docker compose -f compose.hub.yaml -f compose.tokens.yaml up -d --wait
```

**With the chart,** create the Secrets from files (not with `--from-literal`, which puts the secret on the command line), and name them in `tokenSecret` and `envSecret`. Each key of `envSecret` becomes a variable, so keys must be valid variable names:

```fish
oc create secret generic nvflare-wes-tes-tokens --from-file=site-2=site-2.token
oc create secret generic nvflare-wes-oauth --from-file=SITE_1_REFRESH_TOKEN=site-1.refresh-token
helm upgrade hub charts/nvflare-wes-hub --reset-then-reuse-values --set tokenSecret=nvflare-wes-tes-tokens --set envSecret=nvflare-wes-oauth
```

In the sites file, site 2 then has `"token_file": "/run/secrets/tes-tokens/site-2"`. To renew it, replace the Secret: the pod sees the new file within a minute or two, without a restart. A changed `envSecret` takes a restart, which forgets runs ([H2](../testbed/shortcuts.md#h2)):

```fish
oc create secret generic nvflare-wes-tes-tokens --from-file=site-2=site-2.token --dry-run=client -o yaml | oc replace -f -
```

Delete the local files once the Secrets hold them.

### Through proTES

The [stretch goal](../testbed/index.md#goals) ([#18](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/18)): all tasks go to a [proTES](https://github.com/elixir-cloud-aai/proTES), which forwards each one to the TES of its site, and only there. The hub pins each task with proTES's tag `gateway.backends` (`{"type": "allow", "backends": [...]}`, see proTES's [pinning tasks to a TES instance](https://github.com/elixir-cloud-aai/proTES/blob/dev/docs/plugins.md#pinning-tasks-to-a-tes-instance)): by the site's `backend` in the sites file, if it has one, else by the URL of its `tes`. Tasks never go to another TES; if the pinned one is unknown to proTES or doesn't take the task, proTES refuses the task (`503` "No TES instance accepted the task", or `400` for a TES that can't run it), and the run fails. Each `backend` pins one site only: the hub doesn't start with the same `backend` for two sites.

What proTES needs:

- The TES of each site among its TES instances (`custom.tes.backends`), ideally with an identifier (`id`) each, which goes into the site's `backend`; a TES that proTES finds in a registry is pinned by its URL, so leave `backend` out for it. proTES must reach each TES, and each TES must accept proTES's own token (or none).
- Clients may choose TES instances (`plugins.client_backends.enabled`, on by default).
- A token of the hub that proTES accepts, with the role `user`: the hub sends it with every request to proTES, for all sites, and never a site's own token. It doesn't go to the TES of the FL server's task (`FL_SERVER_TES`), which isn't sent through proTES.

What the hub needs:

- `TES_GATEWAY_URL`, the URL of proTES, at `https`; a trailing `/` or `/ga4gh/tes/v1` is dropped.
- `TES_GATEWAY_TOKEN_SOURCE`: a JSON object with one token source, as for a site: `{"token_file": "/run/secrets/tes-tokens/gateway"}`, or `{"oauth": {...}}`. With a `token_file` or `oauth`, a `401` of proTES is retried once with a new token, as for sites. As for sites, a refresh token that the provider rotates is kept in memory only: after a restart, which forgets runs anyway ([H2](../testbed/shortcuts.md#h2)), the hub needs a fresh one, or a `token_file` that something outside the hub renews. The hub doesn't start with a gateway but no token source (the token URL of the local tests aside). On Rahti, set `tesGateway.url` and `tesGateway.tokenFile` (a key of `tokenSecret`) or `tesGateway.oauth` instead.
- `tes` in the sites file stays required, for runs without proTES; a site's own token source isn't used through proTES.

For example, a sites file for a proTES that names the TES of site 2 `site-2` (site 1 is pinned by URL):

```json
{
  "site-1": {"tes": "https://tes.site-1.example.org", "data": "https://data.site-1.example.org/site-1.csv"},
  "site-2": {"tes": "https://tes.site-2.example.org", "backend": "site-2", "data": "https://data.site-2.example.org/site-2.csv"}
}
```

All tasks are then owned in proTES by the one user whose token the hub holds, whoever starts the run ([H25](../testbed/shortcuts.md#h25)).

A TES that takes proTES's own token, a service token of proTES's client rather than the user's, sees that client as the owner of every task that proTES forwards. The user then reads the tasks through proTES only, which has their states and, once they have finished, the logs of the TES; asking the TES directly with the user's token is refused, as the task isn't the user's there. What a plugin of proTES for sites would add is in [A site plugin for proTES](../outcomes/protes-plugin.md).

On Rahti, for a hub that sends its tasks through proTES with a token file (the token in the key `gateway` of a Secret of your own, renewed there without a restart), add these to the update of [Running it on Rahti](#running-it-on-rahti) (Fish):

```fish
helm upgrade hub charts/nvflare-wes-hub --reset-then-reuse-values --set tokenSecret=<secret> --set tesGateway.url=https://<protes> --set tesGateway.tokenFile=gateway
```

### Checking the hub from outside

`tests/outside_check.py` checks a deployed hub as a node, or anyone on the internet, sees it. Run it from a machine outside the hub's network that isn't in `WES_ALLOWED_IPS`, with Python 3.12 or later and a clone of this repository; it needs nothing beyond the standard library. It takes the hub's name, as in the kits, and the host that serves `/kits` and `/sites`: with Compose, both are `FL_SERVER_NAME`.

```sh
python3 tests/outside_check.py [--fl-port <port>] [--admin-port <port>] [--during-run] [--wes-public] [--insecure] [--timeout <seconds>] <hub name> <kits host>
```

| Check | Passes when |
|---|---|
| Both names | They resolve, as an unknown name would pass the checks of closed ports. The hub's name comes without a port: give it with `--fl-port`. The kits host takes `:<port>` if HTTPS isn't on 443 |
| `GET /kits/no-such-token/site-1.tgz` at the kits host | 404 `No such kit`, from the WES: no such kit, but the way is open. A 404 or 503 of a router or proxy fails |
| `POST /sites/no-such-token/csr` at the kits host | 404 `No such token`, from the WES |
| `GET /ga4gh/wes/v1/service-info` at both names; with `--wes-public`, at the hub's name only | Anything but 200, including no answer. Certificates aren't checked here, as any answer counts |
| With `--wes-public` ([the WES API in public](#the-wes-api-in-public)): `GET /ga4gh/wes/v1/service-info` and `GET /ga4gh/wes/v1/runs` without a token, at the kits host | 200, and 401 `Bearer token required` from the WES |
| FL port at the hub's name (`--fl-port`, default 8002) | Open. Outside a run, only the hub's probe responder answers there, which can be switched off, so a closed one is a warning; with `--during-run`, a failure |
| FLARE admin port at the hub's name (`--admin-port`, default 8003) | Closed |

It prints a line for each check, `[ok]`, `[warn]` or `[FAIL]`, and ends with 1 if any failed. It ignores proxy settings such as `HTTPS_PROXY`, as the checks are about what the machine reaches itself, and follows no redirects, so a redirect counts as its own status. It refuses names with a path, ports out of range and timeouts that aren't positive. `--insecure` skips checking certificates, for a hub with a test certificate, as in `tests/hub.sh`; `--help` lists all options. Without a clone, it's in the [image](#the-image): `docker run --rm elixircloud/nvflare-wes-testbed:sha-<commit> python3 /app/tests/outside_check.py …`. CI runs it against the proxy of `tests/hub.sh`, which has the hub's name there, so the port checks meet the proxy, and its unit tests (`python3 tests/outside_check_test.py`).

## What changes in the setup

- A sites file holds the real TES URLs, their tokens, and the [data URLs](#the-test-set).
- `FL_IMAGE` names the [image](#the-image), at a fixed commit.
- `compose.hub.yaml` runs the hub alone, in place of `compose.yaml`; on Rahti, the chart `charts/nvflare-wes-hub` does.
- Only for the [stretch goal](../testbed/index.md#goals): `compose/protes.yaml` lists the real TES instances, with their `auth`.

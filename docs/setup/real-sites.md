# Real sites

!!! warning "Untested"
    None of this has run. It's what we expect it to take: see [T8](../tests/t8-real-sites.md) and the [issues](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues).

## What the hub needs

A public address, with these open: the FL port, straight through to the FL server, as its TLS is mutual, and HTTPS for the links to kits, which nodes fetch. It needs a stable name, set in `FL_SERVER_NAME`: the kits contain it. The WES has no authentication ([H5](../testbed/shortcuts.md#h5)), so only some addresses may reach `/ga4gh/wes/v1`, and `/kits` stays open for nodes.

See [Deploying the hub](#deploying-the-hub) for where it goes, and how.

## What each site needs

- A TES that the WES can call directly, with a token if needed, one per site in the sites file. Only for [stretch goal 2](../testbed/index.md#goals): the TES is known to the proTES in use.
- A task may open connections to the hub's FL port and HTTPS, may pull the public image, and may write to `/tmp`.
- A way to fetch its share of the [test set](#the-test-set) from a public `https` URL.

## The test set

Sites fetch their share from raw files of this repository, at a fixed commit, so the data can't change under a run. These links are public on purpose, which only works because the data is synthetic and describes nobody: see [H13](../testbed/shortcuts.md#h13). **Public or synthetic data only: no clinical data and no data from Trusted Research Environments, ever.**

| Site | `data` in `WES_SITES` | SHA-256 |
|---|---|---|
| First site | [`site-1.csv`](https://raw.githubusercontent.com/elixir-cloud-aai/nvflare-wes-testbed/b473b4b2d3246d6b5f74c31e209268e0c093e062/testset/data/site-1.csv) | `c578295a4bd973bb98fa2def75cffd50313dd9c7ab6b34f6548124a70103c001` |
| Second site | [`site-2.csv`](https://raw.githubusercontent.com/elixir-cloud-aai/nvflare-wes-testbed/b473b4b2d3246d6b5f74c31e209268e0c093e062/testset/data/site-2.csv) | `e1ce32c53696909df438ce665fabe78f384b56ff4ce786d9ecb0101dc754ebca` |

With one site, use the first share. The holdout set isn't for sites: it stays with whoever compares the models.

The shares cover different parts of the feature space: give two sites different ones, or the [expected accuracies](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/blob/dev/testset/README.md) won't hold. `compose.public-data.yaml` runs [T2](../tests/t2-wes-to-tes.md) with these URLs, locally, in CI.

## The image

Nodes pull the one image for all participants: [`elixircloud/nvflare-wes-testbed`](https://hub.docker.com/r/elixircloud/nvflare-wes-testbed). CI builds and pushes it on every push to `dev`, once the tests have passed on a build of its own, as `dev` and as `sha-<commit>`. For a run on real sites, use `sha-<commit>`, as `dev` moves, and set it as `FL_IMAGE`. A fork that sets the repository variable `DOCKERHUB_ORG` uses that organization in place of `elixircloud`. Startup kits, keys and site data stay out of it through `.dockerignore`, which CI checks by file name, with decoys, on a local build. It's a sandbox image, neither signed nor scanned ([H20](../testbed/shortcuts.md#h20)).

## Probing a node

The biggest risk of the plan is whether a task at a node may reach the hub. The probe task finds that out before anyone relies on it, and it decides whether [B1](../testbed/options.md#b1-server-beside-the-wes) works at that node at all. It runs the [image](#the-image), and reports through its log whether it can reach the hub's ports, whether an `https` input arrives, whether `env` is passed, who it runs as, and whether `/tmp` is writable. It handles only the public [test set](#the-test-set), and no keys.

The FL port of a [hub](#what-the-hub-needs) only listens during a run, so start a listener on the machine of the hub first, with the same ports:

```sh
docker run --rm -p 8002:8002 elixircloud/nvflare-wes-testbed:dev python3 /app/tests/probe.py listen 8002
```

Then, on any machine with Docker that can reach the TES:

```sh
docker run --rm -e TES_TOKEN elixircloud/nvflare-wes-testbed:dev \
    python3 /app/tests/probe_submit.py --tes https://<tes> --hub <hub> --fl-port 8002 --ports 443
```

`--fl-port` is the port that decides. `--ports` lists others to try, for information, such as 443 or the port of a [hub on Rahti](#where-it-goes).

`TES_TOKEN` is taken from your environment, if the TES needs a token, and only goes over HTTPS. Through proTES, use its URL as `--tes`, and add `--backend https://<tes>` to pin the task to that TES. proTES keeps no output of tasks, so the script reads it from that TES, which must be reachable with the same token.

| Outcome for a port | Meaning |
|---|---|
| `open` | A task gets there |
| `refused` | Inconclusive: nothing listens, or a firewall rejects the connection |
| `timeout` | Likely blocked by a firewall |
| `unreachable` | No route |
| `no-name` | The name doesn't resolve from the task |

| Last line | Exit code | Meaning |
|---|---|---|
| `[ok]` | 0 | The task completed and reached the FL port, and the input, `env` and `/tmp` work |
| `[FAIL]` | 1 | The node can't take part, as shown above that line |
| `[inconclusive]` | 2 | This doesn't tell: the FL port was `refused`, the log isn't in the task's record (the TES needn't keep it, so ask the operator), the task ran elsewhere than asked for, or it was canceled or still hadn't ended by `--timeout` |

The probe doesn't show that a node can fetch a startup kit from the hub, as its input comes from GitHub: a node with a strict allow-list may differ. That's what question 3 below is for. Record results per node in [Results](../outcomes/results.md), without hostnames. Only local runs against Funnel have been tried, directly and through proTES: see [Tests](../tests/index.md#local-runs).

## What to ask node operators

1. May a TES task connect out to `<hub>:8002`, or `<hub>:443`? Through a proxy?
2. Are there limits on the run time of tasks? A run of the test set takes under a minute.
3. Does the TES need a token to submit tasks, and how does one get it? Which TES version and backend is it? Does it take `http(s)` inputs, and does it have a size limit for them? Does it pass `env` to executors?
4. Can it pull images from Docker Hub, and does it enforce non-root or read-only containers? (Either's fine.)
5. Who has access to task records and logs? They'd see the kit links ([H3](../testbed/shortcuts.md#h3)), for test federations only, which end with the run.

## Deploying the hub

!!! warning "This hasn't run on a real machine"
    `tests/hub.sh` runs `compose.hub.yaml` in CI, with local sites that dial the hub by its name, as an arbitrary non-root user, and it checks what the proxy lets through. `tests/chart.sh` checks the chart for Rahti without a cluster. Certificates from Let's Encrypt, a public port and anything on Rahti or Nebius are untested. What's below about Rahti and Nebius comes from their public docs, read on 2026-11-04. Running it on a machine is [#4](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/4).

### Where it goes

The plan is Rahti if it can expose the FL port, otherwise a VM with Nebius credits.

**Rahti can expose the FL port, on request, and only on a high port.** A Route is for HTTP, so the FL port takes a [`LoadBalancer` Service](https://docs.csc.fi/cloud/rahti/configurations/loadbalancer-service/), which isn't limited to HTTP or HTTPS:

| Way to expose it on Rahti | Works? | What it takes |
|---|---|---|
| `LoadBalancer` Service | Yes, by the docs | A request to the CSC Service Desk, with the Rahti project name, the `csc_project` number, a use case and the number of addresses. The port must be between 30000 and 35000 |
| `NodePort` | No | [NodePorts aren't enabled on Rahti](https://docs.csc.fi/cloud/rahti/configurations/loadbalancer-service/) |
| Passthrough Route on 443, by SNI | Perhaps, untried | [Passthrough leaves TLS to the pod](https://docs.csc.fi/cloud/rahti/usage/networking/), and [Red Hat names it as the way to client certificates](https://docs.redhat.com/en/documentation/openshift_container_platform/4.22/html/ingress_and_load_balancing/routes). Rahti's docs only describe Routes for HTTP. See below |

So on Rahti, `FL_PORT` is, for example, 30002, not 8002 or 443. **Whether tasks at a node may reach such a high port is the open question**, as sites more often allow 443: try it with the [probe](#probing-a-node), with `--fl-port 30002 --ports 8002,443`, and a listener on any machine with those ports open, before settling on Rahti.

What else differs on Rahti:

- Compose doesn't run there: it takes a Deployment, the `LoadBalancer` Service with `allocateLoadBalancerNodePorts: false`, and a Secret for the sites file. The Helm chart [`charts/nvflare-wes-hub`](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/tree/dev/charts/nvflare-wes-hub) has them: see [Running it on Rahti](#running-it-on-rahti).
- **Name:** the kits contain the name of the hub, and it must lead to the address of the `LoadBalancer`. Names under `rahtiapp.fi` should lead to the routers instead, so this takes a name of your own, with an `A` record.
- **Kits:** an edge Route with `path: /kits` exposes the links to kits, and nothing else of the WES. Reach the WES itself with `oc port-forward`, which needs no address list. To limit the FL port to the addresses of nodes, Rahti has a [NetworkPolicy](https://docs.csc.fi/cloud/rahti/configurations/loadbalancer-service/) with `externalTrafficPolicy: Local`. That takes the node selector `rahti.csc.fi/local-load-balancer: ''` on the pod, an address that no other Service shares, and a policy that still lets the router reach the `/kits` Route.
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
| `WES_ALLOWED_IPS` | `127.0.0.1` | Addresses or ranges that reach the WES, separated by spaces |
| `WES_INTERNAL_URL` | `https://<FL_SERVER_NAME>` | Base of the links to kits. Keep it `https`, as kits hold private keys |
| `WES_SITES_FILE` | `./sites.json` | The sites file: name, `tes` and `data`. Add `token` for a TES that needs one, which must then be at an `https` URL |
| `HUB_HTTPS_PORT` | `443` | Another port for HTTPS, if the FL port is 443. Then set `WES_INTERNAL_URL` to match, and Let's Encrypt still needs port 80. The redirect from HTTP still points to 443, so use the `https` URL with its port |

Tokens in the sites file stay out of task records and logs, and the file stays out of Git and of the image. To check the setup, run the [probe](#probing-a-node), then a run with one site ([T8](../tests/t8-real-sites.md)).

### Running it on Rahti

!!! warning "Nothing of this has been tried on Rahti"
    The chart passes `helm lint`, OpenShift's schemas and the checks of `tests/chart.sh`, in CI, without a cluster. It hasn't been installed anywhere: there's no address to try it with yet. Record what differs in [#25](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/25), without hostnames.

The chart [`charts/nvflare-wes-hub`](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/tree/dev/charts/nvflare-wes-hub) holds the hub alone: the thin WES with its FL server, no proxy, no TES. It's a chart rather than plain manifests with Kustomize, as names, port and address are set with `--set`, so nothing about a deployment goes into a file of the repository, and its schema refuses what can't work on Rahti. It makes:

| Object | What it's for |
|---|---|
| Deployment | One pod, replaced, not rolled, on update. As OpenShift's arbitrary user, with `HOME=/tmp`. `hostAliases` lead the hub's name to the pod itself, as `extra_hosts` does in `compose.hub.yaml` |
| `LoadBalancer` Service `…-fl` | The FL port only, with `allocateLoadBalancerNodePorts: false` |
| `ClusterIP` Service `…-wes` | The WES, inside the cluster only |
| Route `…-kits` | `https://<kits name>/kits`, edge TLS, and no other path |

The sites file comes from a Secret that you create, which isn't part of the chart. The WES is not exposed at all: reach it with `oc port-forward`, which needs no address list (in place of `WES_ALLOWED_IPS` and [#5](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/5)). The FLARE admin port stays inside the pod. Other pods of the same Rahti project could still reach the WES and the admin port at the pod's address, so keep the hub in a project of its own.

**Before you start:**

1. **An address from CSC.** Ask the [CSC Service Desk](https://docs.csc.fi/support/contact/), `servicedesk@csc.fi`, for one `LoadBalancer` address for your Rahti project, with the Rahti project name, the `csc_project` number, the use case (a federated learning hub for a BioHackathon sandbox, one TCP port between 30000 and 35000 for connections from compute sites) and the number of addresses: one. It can take some days.
2. **The probe.** Find out whether tasks at the nodes may reach a port that high: [probe them](#probing-a-node) with `--fl-port 30002 --ports 8002,443`, and a listener on any machine with those ports open:

    ```fish
    docker run --rm -p 30002:30002 -p 8002:8002 -p 443:443 elixircloud/nvflare-wes-testbed:sha-<commit> \
        python3 /app/tests/probe.py listen 30002 8002 443
    ```

    If the nodes only let out 443, Rahti won't do: use a VM, [as above](#where-it-goes).
3. **Two names.** The hub's name, of your own, for an `A` record to the address (not under `rahtiapp.fi`, which leads to the routers; the chart refuses it). And a name for the Route of the kits, which leads to the routers: by [Rahti's docs](https://docs.csc.fi/cloud/rahti/usage/networking/), a free name ending in `.rahtiapp.fi` works out of the box, such as `<kits name>.2.rahtiapp.fi`.
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
    --set flPort=30002
oc rollout status deployment/hub-nvflare-wes-hub
oc get service hub-nvflare-wes-hub-fl -o jsonpath='{.status.loadBalancer.ingress[0].ip}'; echo
oc get ipaddresspools.metallb.io -n metallb-system <rahti project> -o jsonpath='{.metadata.annotations.ip_pairs}'; echo
oc get route hub-nvflare-wes-hub-kits -o jsonpath='{.status.ingress[0].conditions[0].type}={.status.ingress[0].conditions[0].status}'; echo
```

**Two addresses:** by the example in [Rahti's docs](https://docs.csc.fi/cloud/rahti/configurations/loadbalancer-service/), the project's pool holds internal addresses (`192.168.…`), and `ip_pairs` pairs each with a public one (`<internal> - <public>`), the one CSC tells you. The Service shows the internal one. **Point the `A` record of the hub's name to the public one**: the kits name it, and sites can't reach the internal one. With more than one address in the pool, pick one with `--set loadBalancerIP=<internal address>`, never the public one, which MetalLB can't assign. Without an address, the Service stays `<pending>`. Without the Secret, the pod waits in `ContainerCreating`.

The Route must say `Admitted=True`. If another project already has its name, the router rejects it (`HostAlreadyClaimed`), and links to kits would lead to someone else's app: pick another `kitsHost`, with `helm upgrade`.

| Value | Default | Meaning |
|---|---|---|
| `image.tag` | None, required | `sha-<commit>` of `dev`, for the hub and the tasks. `dev` is refused, as it moves |
| `hubName` | None, required | `FL_SERVER_NAME`: the hub's name in the kits, with an `A` record to the address |
| `kitsHost` | None, required | Name of the Route for `/kits`, without a scheme. Links to kits are `https://<kitsHost>/kits/…` |
| `flPort` | `30002` | FL port, on the address and in the pod: 30000 to 35000 |
| `flScheme` | `grpc` | `grpc`, or `http` (WebSocket, see [T7](../tests/t7-port-443.md)) |
| `loadBalancerIP` | Empty | Internal address of the project's pool (`192.168.…`), not the public one. Empty: one of the pool's |
| `sitesSecret` | `nvflare-wes-sites` | Secret with the sites file under the key `sites.json` |
| `resources` | 250m CPU and 1 GiB, up to 2 CPUs and 2 GiB | Requests and limits of the pod |

**Reach the WES** (Fish), in a terminal of its own, which keeps the tunnel open:

```fish
oc port-forward service/hub-nvflare-wes-hub-wes 8080:8080
```

Then use `http://localhost:8080/ga4gh/wes/v1` in place of `https://<hub>/ga4gh/wes/v1`, for example in [T8](../tests/t8-real-sites.md). A run goes on in the pod if the tunnel drops.

**Check from outside** (Fish), from a machine outside Rahti:

```fish
set kits <kits name>
set hub <hub name>
set port 30002    # flPort
curl -s -w ' %{http_code} /kits\n' https://$kits/kits/no-such-token/site-1.tgz
curl -s -o /dev/null -w '%{http_code} WES\n' https://$kits/ga4gh/wes/v1/service-info
curl -s -o /dev/null -w '%{http_code} WES\n' https://$hub/ga4gh/wes/v1/service-info
nc -zv -w 5 $hub $port
nc -zv -w 5 $hub 8003
```

`/kits` should give 404 with `{"detail":"No such kit"}`, which comes from the WES: no such kit, but the way is open. The WES must not answer with 200 on either name: the router has no Route for it, and the address has only the FL port. The FL port only listens during a run, so it can read as closed until then. 8003 must stay closed. If the FL port times out during a run although the Service has its address, look for NetworkPolicies of the project (`oc get networkpolicy`) that keep it out: by Rahti's docs, pods only talk to pods of the same project by default.

**Acceptance:** a run with one site ([T8](../tests/t8-real-sites.md)) passes, `/kits` is reachable from outside, and the WES isn't.

**Update or remove it** (Fish). An update restarts the pod, which forgets its runs ([H2](../testbed/shortcuts.md#h2)): check for tasks left at the sites.

```fish
helm upgrade hub charts/nvflare-wes-hub --reuse-values --set image.tag=sha-<commit>
helm uninstall hub
oc delete secret nvflare-wes-sites
```

After editing `sites.json`, replace the Secret and restart the pod:

```fish
oc create secret generic nvflare-wes-sites --from-file=sites.json=sites.json --dry-run=client -o yaml | oc replace -f -
oc rollout restart deployment/hub-nvflare-wes-hub
```

To limit the FL port to the addresses of nodes, Rahti has a [NetworkPolicy with `externalTrafficPolicy: Local`](https://docs.csc.fi/cloud/rahti/configurations/loadbalancer-service/). The chart doesn't do that yet.

## What changes in the setup

- A sites file holds the real TES URLs, their tokens, and the [data URLs](#the-test-set).
- `FL_IMAGE` names the [image](#the-image), at a fixed commit.
- `compose.hub.yaml` runs the hub alone, in place of `compose.yaml`; on Rahti, the chart `charts/nvflare-wes-hub` does.
- Only for [stretch goal 2](../testbed/index.md#goals): `compose/protes.yaml` lists the real TES instances, with their `auth`.

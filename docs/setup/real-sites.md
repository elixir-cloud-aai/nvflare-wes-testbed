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
    `tests/hub.sh` runs `compose.hub.yaml` in CI, with local sites that dial the hub by its name, as an arbitrary non-root user, and it checks what the proxy lets through. Certificates from Let's Encrypt, a public port and anything on Rahti or Nebius are untested. What's below about Rahti and Nebius comes from their public docs, read on 2026-11-04. Running it on a machine is [#4](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/4).

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

- Compose doesn't run there: it takes a Deployment, the `LoadBalancer` Service with `allocateLoadBalancerNodePorts: false`, and a Secret for the sites file. None of it is written, as there's nothing to try it on.
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

## What changes in the setup

- A sites file holds the real TES URLs, their tokens, and the [data URLs](#the-test-set).
- `FL_IMAGE` names the [image](#the-image), at a fixed commit.
- `compose.hub.yaml` runs the hub alone, in place of `compose.yaml`.
- Only for [stretch goal 2](../testbed/index.md#goals): `compose/protes.yaml` lists the real TES instances, with their `auth`.

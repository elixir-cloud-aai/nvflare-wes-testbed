# Real sites

!!! warning "Untested"
    None of this has run. It's what we expect it to take: see [T8](../tests/t8-real-sites.md) and the [issues](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues).

## What the hub needs

A machine with a public address, Docker, and these open: the FL port (8002, or 443 with [T7](../tests/t7-port-443.md)), and HTTPS for the WES, as tasks fetch their kits from it. It needs a stable name, set in `FL_SERVER_NAME` and `WES_INTERNAL_URL`: the kits contain it. The WES has no authentication ([H5](../testbed/shortcuts.md#h5)), so restrict who can reach `/ga4gh/wes/v1`, for example to the addresses of the people at the event, or tunnel to it, and keep the `/kits` path open for nodes.

It goes on [Rahti](https://docs.csc.fi/cloud/rahti/) if that can expose the FL port, otherwise on a plain VM with Nebius credits ([#4](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/4)).

## What each site needs

- A TES that the WES can call directly. The WES sends no credentials to a TES it calls directly, so for now that TES must accept tasks without them ([#4](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/4) adds a token per site). Only for [stretch goal 2](../testbed/index.md#goals): the TES is known to the proTES in use.
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

It needs only Docker, on any machine that can reach the TES. The FL port of a [hub](#what-the-hub-needs) only listens during a run. A port with nothing behind it reports `refused`, which still says that the way there is free.

```sh
docker run --rm -e TES_TOKEN elixircloud/nvflare-wes-testbed:dev \
    python3 /app/tests/probe_submit.py --tes https://<tes> --hub <hub> --ports 8002,443
```

`TES_TOKEN` is taken from your environment, if the TES needs a token. Through proTES, use its URL as `--tes`, and add `--backend https://<tes>` to pin the task to that TES. proTES keeps no output of tasks, so the script reads it from that TES, which must be reachable with the same token.

| Outcome for a port | Meaning |
|---|---|
| `open` | A task gets there |
| `refused` | A task gets there, but nothing listens |
| `timeout` | Likely blocked by a firewall |
| `unreachable` | No route |
| `no-name` | The name doesn't resolve from the task |

It ends with `[ok] the node can take part` if a port was `open`, and the input, `env` and `/tmp` work. If the log isn't in the task's record, it says so: ask the operator. Record results per node in [Results](../outcomes/results.md), without hostnames. Only local runs against Funnel have been tried, directly and through proTES: see [Tests](../tests/index.md#local-runs).

## What to ask node operators

1. May a TES task connect out to `<hub>:8002`, or `<hub>:443`? Through a proxy?
2. Are there limits on the run time of tasks? A run of the test set takes under a minute.
3. Does the TES need a token to submit tasks, and how does one get it? Which TES version and backend is it? Does it take `http(s)` inputs, and does it have a size limit for them? Does it pass `env` to executors?
4. Can it pull images from Docker Hub, and does it enforce non-root or read-only containers? (Either's fine.)
5. Who has access to task records and logs? They'd see the kit links ([H3](../testbed/shortcuts.md#h3)), for test federations only, which end with the run.

## What changes in the setup

- `WES_SITES` holds the real TES URLs, and the [data URLs](#the-test-set).
- `FL_IMAGE` names the [image](#the-image), at a fixed commit.
- Only for [stretch goal 2](../testbed/index.md#goals): `compose/protes.yaml` lists the real TES instances, with their `auth`.

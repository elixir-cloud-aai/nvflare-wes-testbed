# NVFlare on WES and TES testbed

A sandbox that asks one question: can a federated learning job with [NVIDIA FLARE](https://github.com/NVIDIA/NVFlare) (NVFlare) be run through [GA4GH WES](https://github.com/ga4gh/workflow-execution-service-schemas), with its participants scheduled through [GA4GH TES](https://github.com/ga4gh/task-execution-schemas)? It takes all possible shortcuts, and [documents them](testbed/shortcuts.md).

It's work towards milestone M4.5 of ECP work package 4 ("ELIXIR Cloud is available for (selected) ELIXIR users to run federated learning jobs"), whose agreed result is a report based on the GA4GH Cloud AI/ML Working Group.

## Status

!!! warning "This has only run on one laptop, and once on one cluster"
    What ran: a WES run, through a thin WES in this repository, with one NVFlare client per site as a TES task on two local [Funnel](https://github.com/calypr/funnel) instances, also through [proTES](https://github.com/elixir-cloud-aai/proTES), with mutual TLS and a federated model that beats local ones ([results of the local runs](tests/index.md#local-runs)). Once, on 2026-11-12, as a dress rehearsal: the hub on Rahti, with both sites as tasks on one TESK in the same cluster, ending `COMPLETE` ([results](outcomes/results.md)). What didn't: anything at a partner's node, on Poiesis, or in Conquest. There's no authentication, private keys pass through task records, and the "sites" share a kernel. A passing run shows that the pieces fit, and says nothing about whether a real node lets a task reach the FL server.

The [Outcomes](outcomes/open-questions.md) stay empty until the tests have run on real sites, apart from the dress rehearsal in [Results](outcomes/results.md).

## Goals

The main goal is a direct run on real nodes, with the WES calling the TES of each site. Integration with Conquest and with proTES are stretch goals, in that order. See [Goals](testbed/index.md#goals).

## Quick start

Takes a few minutes, mostly for the image builds. It needs Docker with Compose on Linux. No Python on your machine, no free ports, no account. The Funnel containers get the Docker socket: read [`compose.yaml`](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/blob/dev/compose.yaml) first.

```sh
git clone https://github.com/elixir-cloud-aai/nvflare-wes-testbed.git
cd nvflare-wes-testbed
docker compose --profile test build
docker compose --profile test run --rm e2e
docker compose --profile test down -v
```

It ends with `8/8 checks passed`.

## Reading paths

- **For the recommendation, or the M4.5 report:** [Options](testbed/options.md), then [Shortcuts and hacks](testbed/shortcuts.md).
- **To understand the idea:** [Use case](background/use-case.md), [Requirements](background/requirements.md), [Design](background/design.md). These don't depend on any product.
- **To try it on your machine:** [Installation](setup/installation.md), then the [Tests](tests/index.md).
- **To run it on real sites, or as a node operator:** [Real sites](setup/real-sites.md) and [T8](tests/t8-real-sites.md).

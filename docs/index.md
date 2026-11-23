# NVFlare on WES and TES testbed

A sandbox that asks one question: can a federated learning job with [NVIDIA FLARE](https://github.com/NVIDIA/NVFlare) (NVFlare) be run through [GA4GH WES](https://github.com/ga4gh/workflow-execution-service-schemas), with its participants scheduled through [GA4GH TES](https://github.com/ga4gh/task-execution-schemas)? It takes all possible shortcuts, and [documents them](testbed/shortcuts.md).

It's work towards milestone M4.5 of ECP work package 4 ("ELIXIR Cloud is available for (selected) ELIXIR users to run federated learning jobs"), whose agreed result is a report based on the GA4GH Cloud AI/ML Working Group.

## Status

!!! warning "This has only run on laptops, and on one cluster"
    What ran: a WES run, through a thin WES in this repository, with one NVFlare client per site as a TES task on two local [Funnel](https://github.com/calypr/funnel) instances, also through [proTES](https://github.com/elixir-cloud-aai/proTES), with mutual TLS and a federated model that beats local ones ([results of the local runs](tests/index.md#local-runs)). Three times, on 2026-11-12, 2026-11-16 and 2026-11-19, as dress rehearsals: the hub on Rahti, with both sites as tasks on one TESK without authentication in the same cluster, ending `COMPLETE`; the last time, the hub sent an LS Login token to that TESK for each site, which it ignored ([results](outcomes/results.md)). Probes at the DE Node, on 2026-11-21, reached two TES deployments that check tokens; neither can take part as it stands. What didn't run: a run at a node of another organization, a run on a TES that checks tokens, or Poiesis. The WES only takes callers with a token of one trusted OIDC issuer ([H5](testbed/shortcuts.md#h5)), but every caller gets the same role in NVFlare. Sites make their own keys, and only a one-time link for a certificate passes through task records ([H3](testbed/shortcuts.md#h3)). Locally, the "sites" share a kernel. A passing run shows that the pieces fit, and says nothing about whether a real node lets a task reach the FL server.

The [Outcomes](outcomes/open-questions.md) are drafts, from the local runs, the dress rehearsals and the probes; rows from real sites follow from the run with two or more sites ([#10](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/10)).

## Goals

The main goal is a direct run on real nodes, with the WES calling the TES of each site. Integration with proTES is the stretch goal. See [Goals](testbed/index.md#goals).

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

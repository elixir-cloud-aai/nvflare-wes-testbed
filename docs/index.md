# NVFlare on WES and TES testbed

A sandbox that asks one question: can a federated learning job with [NVIDIA FLARE](https://github.com/NVIDIA/NVFlare) (NVFlare) be run through [GA4GH WES](https://github.com/ga4gh/workflow-execution-service-schemas), with its participants scheduled through [GA4GH TES](https://github.com/ga4gh/task-execution-schemas)? It takes all possible shortcuts, and [documents them](testbed/shortcuts.md).

It's work towards milestone M4.5 of ECP work package 4 ("ELIXIR Cloud is available for (selected) ELIXIR users to run federated learning jobs"), whose agreed result is a report based on the GA4GH Cloud AI/ML Working Group.

## Status

!!! warning "This has run once over two Nodes, both with TES of our own"
    On 2026-11-24, a WES run with one NVFlare client per site as a TES task ran over the FI Node's TESK on Rahti and the CZ Node's TESK at CERIT-SC, both checking LS Login tokens, and ended `COMPLETE`, with a federated model as good as in the simulator. Before that: local runs on laptops, with two Funnel instances, also through [proTES](https://github.com/elixir-cloud-aai/proTES) ([results of the local runs](tests/index.md#local-runs)), and three dress rehearsals on Rahti, with both sites on one TESK in the hub's cluster. See the [Report](outcomes/report.md) for the milestones, the evidence and the limitations. Both TES of the run are run by this testbed's maintainers, both are TESK, and the DE Node couldn't join, as its tasks have no way out. The WES only takes callers with a token of one trusted OIDC issuer ([H5](testbed/shortcuts.md#h5)), but every caller gets the same role in NVFlare, and the hub holds one user's token for all sites. Sites make their own keys, and only a one-time link for a certificate passes through task records ([H3](testbed/shortcuts.md#h3)).

The [Outcomes](outcomes/report.md) are drafts: the report, the results, open questions, the gap analysis and proposals.

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

- **For the results, or the M4.5 report:** the [Report](outcomes/report.md), then [Options](testbed/options.md) and [Shortcuts and hacks](testbed/shortcuts.md).
- **To understand the idea:** [Use case](background/use-case.md), [Requirements](background/requirements.md), [Design](background/design.md). These don't depend on any product.
- **To try it on your machine:** [Installation](setup/installation.md), then the [Tests](tests/index.md).
- **To run it on real sites, or as a node operator:** [Real sites](setup/real-sites.md) and [T8](tests/t8-real-sites.md).

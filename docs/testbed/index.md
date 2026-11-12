# Testbed

## Intro

The [Background](../background/use-case.md) describes an end state. This testbed checks how far one can get today, with [NVIDIA FLARE](https://github.com/NVIDIA/NVFlare) for the federated part, and the services of [ELIXIR On-Cloud](https://elixir-on.cloud/) for the rest. It's meant to give the M4.5 report something real to point to, and to be tried at a BioHackathon.

The question is whether a federated job fits WES and TES at all, as TES tasks are batch and FL participants must reach each other. See [Options](options.md) for what was evaluated, and the recommendation. This is a sandbox: see [Shortcuts and hacks](shortcuts.md).

!!! warning "Status: this has only run on one laptop, and once on one cluster"
    See [Home](../index.md#status). Results of the local runs are in [Tests](../tests/index.md#local-runs). The hub has run once on Rahti, with both sites on one TESK in the same cluster: see [Results](../outcomes/results.md). Nothing has run at a partner's node.

## Goals

In this order, each one only after the one before:

1. **Main goal: the direct run.** A WES run on real nodes, with the WES calling the TES of each site directly, and no gateway in between ([#10](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/10)). Fewer things can go wrong that way.
2. **Stretch goal 1: integration with Conquest** ([#12](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/12), [#13](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/13)). See [option A](options.md#a-nvflare-inside-conquest).
3. **Stretch goal 2: integration with proTES** ([#18](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/18)), perhaps with a dedicated plugin later. It already ran locally ([T4](../tests/t4-protes.md)), and isn't a must for the event.

The hub runs on [Rahti](https://docs.csc.fi/cloud/rahti/), which exposes the FL port through a `LoadBalancer` Service; a plain VM with Nebius credits is the fallback ([Real sites](../setup/real-sites.md#where-it-goes), [What differed on Rahti](../setup/real-sites.md#what-differed-on-rahti)).

The session plan ([#8](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/8)) goes under [Order for a live session](../tests/index.md#order-for-a-live-session).

## Scope

**In scope:**

- A WES run that ends with a federated model, with FL participants as TES tasks, on the TES of each site.
- The networking, startup kits, certificates and task lifetimes this takes.
- One minimal job and tiny synthetic data.
- Trying all that on real nodes ([T8](../tests/t8-real-sites.md)).

**Out of scope:**

- Production use, and any real data. **Public or synthetic data only, tiny, with its source and licence stated. No clinical data and no data from Trusted Research Environments, ever, not even as an example.**
- Authentication and access control: the [token exchange testbed](https://github.com/elixir-cloud-aai/token-exchange-flow-testbed) is about that.
- Models and training that are worth anything, and performance.
- NVFlare work inside [Conquest](https://github.com/anuragxxd/conquest) upstream: [option A](options.md#a-nvflare-inside-conquest) is evaluated by reading its code only, and stretch goal 1 stays on a local branch.

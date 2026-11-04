# Testbed

## Intro

The [Background](../background/use-case.md) describes an end state. This testbed checks how far one can get today, with [NVIDIA FLARE](https://github.com/NVIDIA/NVFlare) for the federated part, and the services of [ELIXIR On-Cloud](https://elixir-on.cloud/) for the rest. It's meant to give the M4.5 report something real to point to, and to be tried at a BioHackathon.

The question is whether a federated job fits WES and TES at all, as TES tasks are batch and FL participants must reach each other. See [Options](options.md) for what was evaluated, and the recommendation. This is a sandbox: see [Shortcuts and hacks](shortcuts.md).

!!! warning "Status: this has only run on one laptop"
    See [Home](../index.md#status). Results of the local runs are in [Tests](../tests/index.md#local-runs). Nothing has run on a real site.

## Scope

**In scope:**

- A WES run that ends with a federated model, with FL participants as TES tasks, through a TES gateway.
- The networking, startup kits, certificates and task lifetimes this takes.
- One minimal job and tiny synthetic data.
- Trying all that on real nodes ([T8](../tests/t8-real-sites.md)).

**Out of scope:**

- Production use, and any real data. **Public or synthetic data only, tiny, with its source and licence stated. No clinical data and no data from Trusted Research Environments, ever, not even as an example.**
- Authentication and access control: the [token exchange testbed](https://github.com/elixir-cloud-aai/token-exchange-flow-testbed) is about that.
- Models and training that are worth anything, and performance.
- NVFlare work inside [Conquest](https://github.com/anuragxxd/conquest) upstream: [option A](options.md#a-nvflare-inside-conquest) is evaluated by reading its code only.

# NVFlare on WES and TES testbed

A sandbox for running federated learning jobs with [NVIDIA FLARE](https://github.com/NVIDIA/NVFlare) through [GA4GH WES](https://github.com/ga4gh/workflow-execution-service-schemas) and [TES](https://github.com/ga4gh/task-execution-schemas), and an evaluation of the ways to do that.

> [!WARNING]
> **This has only run on one laptop, against two local Funnel instances. It has not touched a real site.** It has no authentication, sends private keys through task records, and takes every shortcut it can: [all of them are listed](docs/testbed/shortcuts.md). Never for production, and never for real data: its test set is synthetic and tiny.

## Quick start

Needs Docker with Compose, on Linux. No Python on your machine, and no free ports. Takes a few minutes, mostly for the image builds.

```sh
git clone https://github.com/elixir-cloud-aai/nvflare-wes-testbed.git
cd nvflare-wes-testbed
docker compose --profile test build
docker compose --profile test run --rm e2e
docker compose --profile test down -v
```

It ends with `8/8 checks passed`: one WES run, with one TES task per site, and a federated model that beats models trained at either site alone. The Funnel containers get the Docker socket, so read [`compose.yaml`](compose.yaml) first.

## Links

Docs are written for Read the Docs (MkDocs Material), and readable here as Markdown.

- [Home](docs/index.md)
- [Background](docs/background/use-case.md): use case, requirements and design, independent of any product
- [Goals](docs/testbed/index.md#goals): first the direct run, WES to each TES; then Conquest; then proTES
- [Options](docs/testbed/options.md): what was evaluated, and the recommendation
- [Shortcuts and hacks](docs/testbed/shortcuts.md): each with what the proper way would be
- [Setup](docs/setup/installation.md)
- [Tests](docs/tests/index.md)
- [Outcomes](docs/outcomes/open-questions.md): empty until the tests have run on real sites
- [Issues](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues): the work ahead
- [About](docs/about/index.md)

Licence: [Apache-2.0](LICENSE). Never for production.

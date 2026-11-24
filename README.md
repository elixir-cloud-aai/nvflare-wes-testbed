# NVFlare on WES and TES testbed

A sandbox for running federated learning jobs with [NVIDIA FLARE](https://github.com/NVIDIA/NVFlare) through [GA4GH WES](https://github.com/ga4gh/workflow-execution-service-schemas) and [TES](https://github.com/ga4gh/task-execution-schemas), and an evaluation of the ways to do that.

## Milestones

| Milestone | Date | Sites | Auth at the TES | Result |
|---|---|---|---|---|
| First run on one cluster | 2026-11-12 | Both on one TESK, in the hub's cluster on Rahti | None | `COMPLETE` |
| First run with tokens | 2026-11-19 | As above | Sent, not checked | `COMPLETE` |
| First multi-site run | 2026-11-24 | FI Node (TESK on Rahti, CSC) and CZ Node (TESK at CERIT-SC) | LS Login, checked | `COMPLETE`, accuracy 0.975 as in the simulator |

What ran, how, and what it means: the [Report](docs/outcomes/report.md); the raw rows: [Results](docs/outcomes/results.md).

> [!WARNING]
> **A sandbox, and never for production or real data.** Both TES of the multi-site run are run by this testbed's maintainers, both are TESK, and the model and data are toys. Its WES trusts one identity provider and gives every caller the same role, it holds one user's token for all sites, it sends one-time links for certificates through task records, and it takes every shortcut it can: [all of them are listed](docs/testbed/shortcuts.md). Its test set is synthetic and tiny.

## Quick start

Needs Docker with Compose, on Linux. No Python on your machine, and no free ports. Takes a few minutes, mostly for the image builds.

```sh
git clone https://github.com/elixir-cloud-aai/nvflare-wes-testbed.git
cd nvflare-wes-testbed
docker compose --profile test build
docker compose --profile test run --rm e2e
docker compose --profile test down -v
```

It ends with `11/11 checks passed`: one WES run, with one TES task per site, and a federated model that beats models trained at any one site alone. The Funnel containers get the Docker socket, so read [`compose.yaml`](compose.yaml) first.

The same without NVFlare, as rounds of plain TES tasks that need no network ([T10](docs/tests/t10-fedavg.md)): `docker compose --profile test run --rm fedavg-e2e`, before `down`. It ends with `18/18 checks passed`.

## Links

Docs are written for Read the Docs (MkDocs Material), and readable here as Markdown.

- [Home](docs/index.md)
- [Background](docs/background/use-case.md): use case, requirements and design, independent of any product
- [Goals](docs/testbed/index.md#goals): first the direct run, WES to each TES; then proTES
- [Options](docs/testbed/options.md): what was evaluated, and the recommendation
- [Shortcuts and hacks](docs/testbed/shortcuts.md): each with what the proper way would be
- [Setup](docs/setup/installation.md)
- [Tests](docs/tests/index.md)
- [Outcomes](docs/outcomes/report.md): the report of results and discussion, and drafts of open questions, gaps and proposals
- [Issues](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues): the work ahead
- [About](docs/about/index.md)

Licence: [Apache-2.0](LICENSE). Never for production.

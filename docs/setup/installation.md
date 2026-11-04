# Requirements and installation

## Requirements

- Docker with Compose. Ran on Docker 28.3, on Linux. Multiple `--network` options on `docker run` need Docker 25 or later ([T5](../tests/t5-server-task.md) only).
- About 1 GB of disk for the images, and 3 GB more for proTES ([T4](../tests/t4-protes.md)).
- Nothing else: no Python on your machine, no free ports, no account.

!!! warning "The Docker socket"
    Funnel gets the Docker socket, to start the containers of tasks. That amounts to root on your machine: read [`compose.yaml`](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/blob/dev/compose.yaml) first. See [H9](../testbed/shortcuts.md#h9).

## Installation

```sh
git clone https://github.com/elixir-cloud-aai/nvflare-wes-testbed.git
cd nvflare-wes-testbed
docker compose --profile test build
```

## Checking the setup

```sh
docker compose --profile test run --rm e2e
```

It ends with `8/8 checks passed`, in under a minute once the images are built. This is [T2](../tests/t2-wes-to-tes.md).

## Cleaning up

```sh
docker compose --profile test down -v
```

Task containers are removed by Funnel when they end, and have the label `nvflare-wes-testbed=task`. If a run was interrupted:

```sh
docker ps -q --filter label=nvflare-wes-testbed=task | xargs -r docker rm -f
```

Funnel's work directories are in `/tmp/nvflare-wes-testbed/`, owned by root, and empty after a run.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| A task ends with `EXECUTOR_ERROR` right away | The image is missing: run the build. Funnel looks for it locally, and pulls nothing |
| `SYSTEM_ERROR` with `Sites joined: []` | Clients can't reach the hub. See `docker compose logs funnel-site-1` |
| Runs get `409` | One run at a time ([H2](../testbed/shortcuts.md#h2)) |
| Port conflicts | There should be none, as nothing is published on the host |

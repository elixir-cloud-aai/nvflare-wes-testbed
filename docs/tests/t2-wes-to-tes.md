# T2 WES to TES

## Description

The core of [B1](../testbed/options.md#b1-server-beside-the-wes): a WES run, with an FL client per site as a TES task on two Funnel instances, and the FL server beside the WES. See [One run](../testbed/design.md#one-run).

## Expectations

1. The WES advertises `NVFLARE`.
2. The run goes through `RUNNING` to `COMPLETE`, and the FLARE job to `FINISHED:COMPLETED`.
3. There's one TES task per site, each `COMPLETE`: the clients ended without errors, after the shutdown through the admin API.
4. The global model can be downloaded, and beats models trained at either site alone on the holdout set.
5. The links to the kits are dead after the run.

## Steps

```sh
docker compose --profile test run --rm e2e
```

To follow a client, in another terminal:

```sh
docker compose logs -f funnel-site-1
```

It ends with `8/8 checks passed`. With the data at [public URLs](../setup/real-sites.md#the-test-set), as on real sites, add `-f compose.yaml -f compose.public-data.yaml` after `docker compose`, and it ends with `10/10 checks passed`, as it also checks where the data came from.

To see the connections on the server's side during a run:

```sh
docker compose exec fl-hub sh -c 'grep "Connection \[" /tmp/wes/*/server.log'
```

Connections from different subnets, with the names `site-1` and `site-2`, show that the clients dialled out from their networks, with TLS.

## Questions it answers

- Can a TES task carry a client for the length of a job, and end properly?
- Do startup kits as task inputs work?
- Does a WES run map onto a federation?

## What to record

Output of the run; how long it took; states of the tasks.

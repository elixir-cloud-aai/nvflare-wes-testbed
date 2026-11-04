# T3 Isolation

## Description

What's between the participants. Each site is a Docker network without a route out, standing in for a site's firewall ([H19](../testbed/shortcuts.md#h19)). A test container on a site's network plays the part of a task. Clients need only reach out: see [How NVFlare fits](../testbed/options.md#how-nvflare-fits).

## Expectations

1. From each site's network, the hub is reachable.
2. The other site's TES and the internet aren't.
3. There's no data on the hub: its container has no CSV files of the sites.
4. Clients open connections to the server only, as the log says `ACTIVE grpc://fl-hub:8002`. During a run, a client's container listens on the loopback interface only.

## Steps

```sh
docker compose --profile test run --rm probe-site-1
docker compose --profile test run --rm probe-site-2
docker compose up -d --wait fl-hub
docker compose exec fl-hub sh -c 'find / -name "site-*.csv" -not -path "/proc/*" 2>/dev/null | wc -l'
```

The last line prints `0`. After a run ([T2](t2-wes-to-tes.md)):

```sh
docker compose logs funnel-site-1 | grep -o 'ACTIVE [a-z]*://[^ ]*' | sort -u
```

To see a client's listening sockets during a run, look for state `0A` in `/proc/net/tcp` of its container, found with `docker ps --filter label=nvflare-wes-testbed=task`.

## Questions it answers

- Does a federated run need any way into a site? It doesn't.
- Does the data pass through the WES? It doesn't: the WES only has its URL.

## What to record

Output of the probes. On a real node, whether the same holds: that's question one of [T8](t8-real-sites.md).

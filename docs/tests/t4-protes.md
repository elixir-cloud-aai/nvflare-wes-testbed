# T4 Through proTES

## Description

As [T2](t2-wes-to-tes.md), with tasks sent to [proTES](https://github.com/elixir-cloud-aai/proTES) instead of directly to the TES of a site. Each task has the tag [`gateway.backends`](https://github.com/elixir-cloud-aai/proTES/blob/dev/docs/plugins.md#choices-of-clients), which lets proTES use only the TES of that site ([H11](../testbed/shortcuts.md#h11)). Without it, a client could land on the wrong site, and not find its data. proTES uses a [fake identity provider](../testbed/shortcuts.md#h10) here.

## Expectations

1. As in T2.
2. For each task, proTES's tag `gateway.backend` is the TES of its site.

## Steps

```sh
docker compose -f compose.yaml -f compose.protes.yaml --profile test build
docker compose -f compose.yaml -f compose.protes.yaml --profile test run --rm e2e
docker compose -f compose.yaml -f compose.protes.yaml --profile test down -v
```

It ends with `10/10 checks passed`. The first build takes a few minutes, as it builds proTES from its repository.

## Questions it answers

- Does proTES pass on tasks with kit links and site-local data URLs? It does, with the settings of `compose/protes.yaml`.
- Can a client choose a site without any change to proTES? It can.

## What to record

Tags of the tasks; whether site URLs had to be listed differently than expected.

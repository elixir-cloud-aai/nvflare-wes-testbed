# T5 Server as a TES task

## Description

[B2](../testbed/options.md#b2-server-as-a-tes-task-too): all participants are TES tasks, the server on a third Funnel. This works only because that Funnel gives its executors the name `fl-server` on the networks of the sites ([H6](../testbed/shortcuts.md#h6)). No TES offers that. This test shows what's missing from TES more than it shows what works.

## Expectations

1. As in T2, with one task more, `fl-server`, also `COMPLETE`.

## Steps

```sh
docker compose -f compose.yaml -f compose.server-task.yaml --profile test build
docker compose -f compose.yaml -f compose.server-task.yaml --profile test run --rm e2e
docker compose -f compose.yaml -f compose.server-task.yaml --profile test down -v
```

It ends with `8/8 checks passed`.

## Questions it answers

- Is a server in a TES task a problem for NVFlare? It isn't, if it has a known name.
- What's needed from TES for this on real nodes? A way to ask for an address, a name and a port.

## What to record

Whether a real node has any way to offer this, in case the question comes up at the event. Don't plan on it.

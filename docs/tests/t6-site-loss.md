# T6 Losing a site

## Description

The client of site 2 gets killed in the middle of a run, as if a node had gone down. Clients don't come back ([H18](../testbed/shortcuts.md#h18)). What matters is that nothing hangs, and nothing keeps running. Left to itself, the job would wait for the lost site until it times out, so the WES watches the tasks.

## Expectations

1. The run ends with `SYSTEM_ERROR`, within seconds, and says why.
2. The client of the other site is canceled, and no task containers are left.
3. The next run works.

## Steps

```sh
docker compose --profile test build
docker compose up -d --wait fl-hub
tests/site-loss.sh
docker compose --profile test run --rm e2e
docker compose --profile test down -v
```

## Questions it answers

What does a user see when a node fails, and does the federation clean up after itself?

## What to record

Time from the kill to the end of the run; anything that stayed behind.

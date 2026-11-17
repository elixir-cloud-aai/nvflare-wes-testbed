# T10 FedAvg as a plain workflow

## Description

[C4](../testbed/options.md#c4-fedavg-as-a-plain-workflow), in the testbed's own WES: a run of workflow type `FEDAVG`, without NVFlare. Each round is one TES task per site, on the two Funnel instances, and the WES averages the updates. A task gets the current model inline, as the `content` of an input, and its data by a URL that only resolves at the site, trains, prints its update, and ends. The WES reads the update from the task's record at the TES of the site. No participant listens anywhere, so there's no FL port, no link to the hub, and no token or key in any task record. What that costs in privacy is in [H24](../testbed/shortcuts.md#h24). See [A plain FedAvg run](../testbed/design.md#a-plain-fedavg-run).

## Expectations

1. The WES advertises `FEDAVG`, and refuses an unknown workload, one named by a path, and a number of rounds out of range (`400`).
2. A run of 5 rounds, as many as the NVFlare job of [T1](t1-simulator.md), goes to `COMPLETE`.
3. There's one TES task per site and round, each `COMPLETE`, at the TES of its site.
4. The global model can be downloaded, and beats models trained at either site alone on the holdout set, as in T1: `federated 0.975, site-1 alone 0.825, site-2 alone 0.875`.
5. The records of the tasks name no hub, link or token, a task fetches nothing but its data, and its output holds its update.

`tests/fedavg_check.py` checks the rest against a fake TES, with no network: rounds chain (each gets the average of the last, weighted by the rows of each site), a failed task or a bad update ends the run as `EXECUTOR_ERROR` at once, also while other tasks of the round still run, without echoing what the task printed, and a round that doesn't end in time fails the run, and cancels its tasks. It also checks that malformed requests get `400` without starting a run, and that a site's round trains exactly as the NVFlare client of T2 does. `tests/fedavg_test.py` unit-tests `wes/fedavg.py`, the parsing of updates included, with no image.

## Steps

```sh
docker compose --profile test build
python3 tests/fedavg_test.py
docker compose --profile test run --rm -T fedavg-check
docker compose --profile test run --rm -T fedavg-e2e
docker compose --profile test down -v
```

`fedavg-check` ends with `28/28 checks passed`, `fedavg-e2e` with `18/18 checks passed`. A run takes about 12 seconds, as each round costs a task start at each site.

To submit a run by hand, as in [T8](t8-real-sites.md), with `workflow_type=FEDAVG`, `workflow_type_version=1.0`, `workflow_url=logreg`, and optionally `workflow_params={"sites": ["site-1", "site-2"], "rounds": 5}` (1 to 20 rounds).

## Questions it answers

- Does federated learning work through WES and TES as they are, with tasks that just end, and no network between participants?
- Does it get the same model as NVFlare, with the same test set?
- What does a site's TES keep of a run?

## What to record

Output of the run; how long it took; states of the tasks. On a real node: whether its TES keeps the output of a task (`stdout` in view `FULL`), and how much of it.

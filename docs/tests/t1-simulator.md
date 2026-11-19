# T1 Simulator

## Description

The job in NVFlare's simulator: no network, no TES, no WES. Shows that the test set works by itself, and is the baseline for the rest. **This isn't federated:** all data is in one place, which is the point of [C1](../testbed/options.md#c1-the-simulator-in-one-task)'s warning.

## Expectations

1. The job finishes 5 rounds.
2. It prints `holdout accuracy: federated 0.975, site-1 alone 0.825, site-2 alone 0.875, site-3 alone 0.925, site-4 alone 0.900`, and exits with 0: the federated model beats a model trained on any one share of the test set alone, also on the shares of sites 3 and 4, which aren't in this run.

## Steps

```sh
docker compose --profile test run --rm simulator
```

With three sites, and the job `logreg-fedavg-3`, it prints `federated 0.975` as well:

```sh
docker compose -f compose.yaml -f compose.three-sites.yaml --profile test run --rm simulator
```

With four sites, and the job `logreg-fedavg-4`, it prints `federated 1.000`; it needs no Funnel, so only the command changes:

```sh
docker compose --profile test run --rm simulator 'python job.py --workspace /tmp/sim --rounds 5 --sites 4 && python /app/testset/evaluate.py /tmp/sim/logreg-fedavg-4/server/simulate_job/models/server.npy --data /data --expect 1.000'
```

`docker compose --profile test run --rm evaluate-check` checks the comparison itself (shares found by number, at least two, and `--expect`), the names of the jobs, and that each job's FedAvg asks all its sites each round (`num_clients` equals `min_clients`). CI runs all of these.

## Questions it answers

Do the job and data work with this version of NVFlare?

## What to record

The accuracies, and the version of NVFlare.

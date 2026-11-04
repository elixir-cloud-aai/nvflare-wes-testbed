# T1 Simulator

## Description

The job in NVFlare's simulator: no network, no TES, no WES. Shows that the test set works by itself, and is the baseline for the rest. **This isn't federated:** all data is in one place, which is the point of [C1](../testbed/options.md#c1-the-simulator-in-one-task)'s warning.

## Expectations

1. The job finishes 5 rounds.
2. It prints `holdout accuracy: federated 0.975, site-1 alone 0.825, site-2 alone 0.875`, and exits with 0.

## Steps

```sh
docker compose --profile test run --rm simulator
```

## Questions it answers

Do the job and data work with this version of NVFlare?

## What to record

The accuracies, and the version of NVFlare.

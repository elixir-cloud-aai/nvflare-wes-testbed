# Tests

!!! warning "Expected results are not observations"
    Local runs say that the pieces fit. They say nothing about real nodes. On a real site, whatever differs from an expectation is a result: record it.

## The tests

| Test | What it shows | Where | CI |
|---|---|---|---|
| [T1 Simulator](t1-simulator.md) | The job and data work, without any service | Local | Yes |
| [T2 WES to TES](t2-wes-to-tes.md) | A WES run with clients as TES tasks ends with a model | Local | Yes |
| [T3 Isolation](t3-isolation.md) | Tasks reach the hub only; data doesn't reach the hub | Local | Yes |
| [T4 Through proTES](t4-protes.md) | The same through a gateway, with tasks pinned to sites ([stretch goal 2](../testbed/index.md#goals)) | Local | No (slow build) |
| [T5 Server as a TES task](t5-server-task.md) | What it takes to have all participants as TES tasks | Local | No |
| [T6 Losing a site](t6-site-loss.md) | A run fails soon and cleanly if a client dies | Local | Yes |
| [T7 Only port 443](t7-port-443.md) | Works with a port that's more often open | Local | No |
| [T8 Real sites](t8-real-sites.md) | The direct run, on real nodes. Conquest and proTES are [tracked separately](../testbed/index.md#goals) | Event | No |

## Order for a live session

The [goals](../testbed/index.md#goals) set the order: first the direct run, with the WES calling each TES. Conquest and proTES only follow if that's done. The session plan ([#8](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/8)) goes here.

Prepare, as early as possible:

1. Run T2 locally, on the machine that will be the hub.
2. Run the probe task on each node ([#2](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/2), [#3](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/3)), so that the session isn't spent finding out what's blocked.
3. Have one operator per node at hand.

Then: T8, with T7's port if T3's question came out badly. If that's a dead end at all nodes, stop and record it: that's a result, too. Then [C4](../testbed/options.md#c4-fedavg-as-a-plain-workflow) is the way forward.

## Local runs

On 2026-11-04, on one laptop with Docker 28.3, with NVFlare 2.9.0 from PyPI, Funnel v0.11.14 and proTES v0.4.0, with the test set. No real site was involved.

| Test | Result |
|---|---|
| T1 | Ran. Holdout accuracy: federated 0.975, site 1 alone 0.825, site 2 alone 0.875 |
| T2 | 8/8 checks; about 45 seconds from request to `COMPLETE`, with the same accuracies |
| T2, tasks as non-root (one-off change of the run template) | 8/8 checks |
| T3 | Ran: hub reachable, the other site and the internet not. No data on the hub. A client listens on the loopback interface only (127.0.0.1 and Docker's resolver at 127.0.0.11) |
| T4 | 10/10 checks, tasks at the TES of their sites |
| T5 | 8/8 checks, with the hacked TES |
| T6 | Run ended `SYSTEM_ERROR` about 6 seconds after the kill. No task containers left |
| T7 | 8/8 checks, with `http` (WebSocket) on port 443 |
| Node probe (`tests/probe-node.sh`) | Ran against the local Funnel of site 1, directly and through proTES. Tells a node that can take part from one that can't |
| Hub of `compose.hub.yaml` (`tests/hub.sh`) | 10/10 checks with local sites, as an arbitrary non-root user. The proxy passes `/kits` and `/sites`, and the WES only from allowed addresses. The [checks from outside](../setup/real-sites.md#checking-the-hub-from-outside) pass, with a warning for the FL port outside a run, and fail on the WES alone once it's open to all |
| FL port held (`tests/fl_port_check.py`, in `tests/hub.sh`) | 13/13 checks outside the image, with NVFlare stubbed: a run with the FL port held fails at once and submits no tasks, a port that can't be bound for another reason isn't called in use, a failed bind in the server log is refused (also when logged after the admin port), and a run with the FL server in a TES task skips the check. In the image: in CI |
| Checks from outside (`tests/outside_check_test.py`) | Unit tests of `tests/outside_check.py`, with a local server and mocks, in CI |
| Chart for Rahti (`tests/chart.sh`) | Lint, what it exposes and refuses, a CPU limit at most 5 times the request, and OpenShift's schemas, in CI, without a cluster. Installed on Rahti on 2026-11-12: see [What differed on Rahti](../setup/real-sites.md#what-differed-on-rahti) |
| T8 | Not a local run: on Rahti, 2026-11-12, with both sites on one TESK in the hub's cluster. The first run: `SYSTEM_ERROR` after the start timeout, no site joined. The node probe's listener, left running in the hub's pod, held the FL port, and the FL server started without it. Runs now fail at once in that case. After a restart of the pod: `COMPLETE`, accuracies not checked. See [Results](../outcomes/results.md) |

# T8 Real sites

!!! warning "Not run"
    Planned for the event. See [Real sites](../setup/real-sites.md) for what it takes.

## Description

[T2](t2-wes-to-tes.md) or [T4](t4-protes.md), with the hub on a reachable machine and clients on TES instances of real nodes. One node is worth having; two make it federated across organizations. **Test set only: public or synthetic data, no clinical data and no data from Trusted Research Environments, ever.**

## Expectations

These are what we hope for. Anything else is a result.

1. A probe task at each node reaches the hub's port.
2. The node runs the image, with kit and data as inputs.
3. The client registers with the server, and the job finishes.
4. The accuracies are those of T1, as the job and data are the same.
5. The task's record at the node says `COMPLETE`.

## Steps

1. Deploy the hub, following [Real sites](../setup/real-sites.md).
2. Run the probe task at each node.
3. Start a run with one site, then with two:

    ```sh
    curl -F workflow_type=NVFLARE -F workflow_type_version=2.9 \
        -F workflow_url=logreg-fedavg \
        -F 'workflow_params={"sites": ["<site>"]}' \
        https://<hub>/ga4gh/wes/v1/runs
    ```

    The job has `min_clients: 2`: with one site, export it with `min_clients` of 1 first.

4. Follow it with `GET /ga4gh/wes/v1/runs/<id>`, and at the node with its operator.

## Questions it answers

- Does a TES task at this node get out? Through what?
- Does anything differ from Funnel? TES version, inputs, `env`, file systems, users.
- How long does a task take to start at a node, and does that matter to the job's timeouts?
- What do operators think of it? Would they rather run a [long-running client](../testbed/options.md#c2-a-fixed-nvflare-network)?

## What to record

For each node, without hostnames or anything internal: TES implementation and version; what was needed to get out; start time of a task; results of the run; what the operator said. Put it in [Results](../outcomes/results.md).

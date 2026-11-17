# Testbed design

The design of [B1](options.md#b1-server-beside-the-wes), the recommended option, with the WES calling the TES of each site directly. The dashed path through proTES is the [stretch goal](index.md#goals). Compared to the [ideal design](../background/design.md), it has a hub in place of a rendezvous service, and credentials made centrally. All that's listed under [Shortcuts and hacks](shortcuts.md).

```mermaid
flowchart LR
    U[e2e: the researcher] -- "WES run" --> W
    subgraph hub [fl-hub]
      W[Thin WES] -- "child process" --> S[FL server]
    end
    W -- "TES task" --> F1
    W -- "TES task" --> F2
    W -. "stretch goal: pinned by tag" .-> P[proTES]
    P -.-> F1
    P -.-> F2
    subgraph s1 [site-1: no way out but to the hub]
      F1[Funnel] --> C1[FL client]
      D1[(site-1.csv)] --> F1
    end
    subgraph s2 [site-2: no way out but to the hub]
      F2[Funnel] --> C2[FL client]
      D2[(site-2.csv)] --> F2
    end
    C1 -- "dials out, mutual TLS" --> S
    C2 -- "dials out, mutual TLS" --> S
    W -- "FLARE admin API" --> S
```

## One run

1. **Request:** `POST /ga4gh/wes/v1/runs`, with a bearer token from the trusted OIDC issuer (`WES_OIDC_ISSUER`), and `workflow_type=NVFLARE`, `workflow_url=logreg-fedavg`, and optional `workflow_params` naming the sites.
2. **Federation:** the WES writes a `project_profile.yaml`, and runs `nvflare cert init`: a new root CA for this run alone. It then provisions the server and an admin itself, through `nvflare cert request`, `approve` and `package` run locally, one after another, the admin named after the caller's validated identity (its token's `sub`).
3. **Server:** the WES starts it as a child process, and waits for its admin port.
4. **Clients:** per site, the WES submits a TES task with one input, the data, by a URL that only resolves at the site, and a one-time link to sign a certificate (`/sites/{token}/csr`). The task goes straight to the TES of the site. Only through proTES (`TES_GATEWAY_URL` set), the tag `gateway.backends` pins it there.
5. **Join:** Funnel fetches the data, and starts the image. The client makes its own key, sends the WES a signing request over its one-time link, and finishes provisioning itself with the certificate that comes back, checking the CA's fingerprint out of band first. It then dials out to `fl-hub:8002`, and blocks. The WES waits until all sites are registered, or a task has ended early.
6. **Job:** the WES submits the job through the FLARE admin API, and waits for it, watching the tasks meanwhile.
7. **End:** the WES downloads the global model, and shuts the federation down through the admin API, so that the client processes exit and the tasks end as `COMPLETE`. It deletes the run's CA and any signing slot not already used.

The run is `COMPLETE` if the job finished, and there's a model, and all tasks are `COMPLETE`. It's `SYSTEM_ERROR` if anything failed, and all remaining tasks are canceled.

## A plain FedAvg run

[C4](options.md#c4-fedavg-as-a-plain-workflow), without NVFlare, through the same WES and the same sites ([T10](../tests/t10-fedavg.md)):

1. **Request:** as above, with `workflow_type=FEDAVG`, `workflow_type_version=1.0`, `workflow_url=logreg` (the one workload in the image), and optional `workflow_params` naming the sites and the number of rounds (`rounds`, 1 to 20, by default 5, as the NVFlare job).
2. **Round:** per site, the WES submits a TES task with two inputs: the data, by a URL that only resolves at the site, as above, and the current model, inline (`content`). Through proTES, the tag `gateway.backends` pins it to its site, as above. The task trains the same logistic regression as the NVFlare job, prints its update (`FEDAVG_UPDATE {"weights": [...], "rows": n}`), and ends. It needs no network but to read its data.
3. **Average:** once all tasks of the round are `COMPLETE`, the WES reads each update from the task's record at the TES of its site (view `FULL`), checks it, and averages the updates, weighted by rows. The next round starts from that model.
4. **End:** after the last round, the WES keeps the model, for download as with `NVFLARE`.

The run is `COMPLETE` if all rounds ended with a model. It's `EXECUTOR_ERROR` as soon as a task fails, or prints no usable update, and `SYSTEM_ERROR` if anything else failed, such as a round that didn't end within `FEDAVG_ROUND_TIMEOUT` seconds (by default 300); remaining tasks are canceled. The FL port, and the probe responder on it, aren't touched. What the records of the tasks give away is in [H24](shortcuts.md#h24).

## Files

```text
wes/app.py                 thin WES
wes/fedavg.py              plain FedAvg workflow type (C4)
images/                    images, and the wrappers for the participants
testset/                   data, job, plain FedAvg round, comparison with local models
compose.yaml               the testbed: hub, two sites, tests
compose.protes.yaml        override: through proTES (T4)
compose.server-task.yaml   override: server as a TES task (T5)
compose.hub.yaml           the hub alone, for a machine with a public address
compose/                   configs of Funnel, proTES and the hub's reverse proxy
tests/                     e2e (T2, T4, T5, T7, T10), probe (T3), site loss (T6), image contents, node probe
```

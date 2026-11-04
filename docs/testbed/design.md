# Testbed design

The design of [B1](options.md#b1-server-beside-the-wes), the recommended option, with the WES calling the TES of each site directly. The dashed path through proTES is [stretch goal 2](index.md#goals). Compared to the [ideal design](../background/design.md), it has a hub in place of a rendezvous service, and credentials made centrally. All that's listed under [Shortcuts and hacks](shortcuts.md).

```mermaid
flowchart LR
    U[e2e: the researcher] -- "WES run" --> W
    subgraph hub [fl-hub]
      W[Thin WES] -- "child process" --> S[FL server]
    end
    W -- "TES task" --> F1
    W -- "TES task" --> F2
    W -. "stretch goal 2: pinned by tag" .-> P[proTES]
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

1. **Request:** `POST /ga4gh/wes/v1/runs` with `workflow_type=NVFLARE`, `workflow_url=logreg-fedavg`, and optional `workflow_params` naming the sites.
2. **Federation:** the WES writes a `project.yml`, and runs `nvflare provision`: a new root CA and a kit each for the server, the sites and an admin, for this run alone.
3. **Server:** the WES starts it as a child process, and waits for its admin port.
4. **Clients:** per site, the WES submits a TES task with two inputs: the kit from an unguessable link at the WES, and the data, by a URL that only resolves at the site. The task goes straight to the TES of the site. Only through proTES (`TES_GATEWAY_URL` set), the tag `gateway.backends` pins it there.
5. **Join:** Funnel fetches the inputs, and starts the image. The client unpacks its kit into `/tmp`, dials out to `fl-hub:8002`, and blocks. The WES waits until all sites are registered, or a task has ended early.
6. **Job:** the WES submits the job through the FLARE admin API, and waits for it, watching the tasks meanwhile.
7. **End:** the WES downloads the global model, and shuts the federation down through the admin API, so that the client processes exit and the tasks end as `COMPLETE`. It removes the kits and their links.

The run is `COMPLETE` if the job finished, and there's a model, and all tasks are `COMPLETE`. It's `SYSTEM_ERROR` if anything failed, and all remaining tasks are canceled.

## Files

```text
wes/app.py                 thin WES
images/                    images, and the wrappers for the participants
testset/                   data, job, comparison with local models
compose.yaml               the testbed: hub, two sites, tests
compose.protes.yaml        override: through proTES (T4)
compose.server-task.yaml   override: server as a TES task (T5)
compose/                   configs of Funnel and proTES
tests/                     e2e (T2, T4, T5, T7), probe (T3), site loss (T6), image contents, node probe
```

# Options

Effort is in hours for one person, for a first demonstration, as local work on this testbed went faster than expected: the recommended path took under two hours up to the local run. Time of node operators comes on top, and may well dominate. "Ran" means it ran in this repository, see [Tests](../tests/index.md#local-runs); anything else comes from reading code and docs.

## Summary

| Option | Reaches real sites? | Runs NVFlare? | Needs from sites | Effort (hours) | Status |
|---|---|---|---|---|---|
| [A1 Workflow type in Conquest](#a1-a-new-workflow-type) | Only after Conquest can use an external TES | Yes | Egress to the server, after that | 8 to 13 | Read only |
| [A2 Workflow steps in Conquest](#a2-nvflare-as-workflow-steps) | Same | Yes | Same | 5 to 8 | Read only |
| [**B1 Thin WES, server beside it, clients as TES tasks**](#b1-server-beside-the-wes) | **Yes** | **Yes** | **Egress to one port** | **4 to 8 more** | **Ran locally, also through proTES** |
| [B2 Same, with the server as a TES task](#b2-server-as-a-tes-task-too) | Hardly: tasks have no reachable address | Yes | Inbound to a task | 2 to 4 more, plus a relay | Ran locally, on a hacked TES |
| [C1 Simulator in one task](#c1-the-simulator-in-one-task) | Not federated | Simulator only | Nothing | 1 | Simulator ran; not as a TES task |
| [C2 Fixed NVFlare network, WES only submits](#c2-a-fixed-nvflare-network) | Yes | Yes | Long-running client per site | 3 to 4 | Read only |
| [C3 A TES job launcher for NVFlare](#c3-a-tes-job-launcher-in-nvflare) | Yes | Yes | Long-running client per site, inbound from tasks | 12 to 20 | Read only |
| [C4 FedAvg as a plain workflow, without NVFlare](#c4-fedavg-as-a-plain-workflow) | Yes | **No** | Nothing new | 3 to 5 | Read only |

## Recommendation

**B1**, with the WES calling the TES of each site directly, as [decided](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/9) for the event. C4 is the fallback, and A comes once Conquest can use an external TES. Going through proTES isn't part of the recommendation: it's [stretch goal 2](index.md#goals), and T4 shows that it works locally.

- It's the only option that ran, across TES instances and through proTES, that needs nothing from a site beyond a task that can dial out to one port. FLARE clients only dial out ([T3](../tests/t3-isolation.md)), and that port can be 443 ([T7](../tests/t7-port-443.md)).
- Everything it hacks is ours, and listed. It needs nothing from anyone else's roadmap, so it can be tried at the event.
- Its logic is a port away from Conquest, should [option A](#a-nvflare-inside-conquest) become attractive: the steps of a run are the same, with a Go adapter and a runner image instead of a thin service.
- Its risk is at the sites, not in the software: whether a task at a real node may reach the hub. So the first thing to do is to find that out, with a probe task ([#2](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/2)). If nodes don't allow it, C4 still gets a federated model through the same services, but without NVFlare.

**What this means for the M4.5 report:** it can point to a run through standard APIs across TES instances, with NVFlare, and to a clear list of what's missing. It can't claim that "ELIXIR Cloud is available" for this: there's no authentication, one run at a time, and keys travel in task records. A real-site run at the event would make it a demonstration on real nodes; without one, it's a local proof of concept and an architecture analysis.

## How NVFlare fits

What was found in NVFlare 2.9.0 ([docs and code](../about/references.md#nvflare)), and in the runs here:

- **Networking:** clients dial out to the server, on one port, with mutual TLS by default. During a run, they listen on the loopback interface only ([T3](../tests/t3-isolation.md)). Clients needn't reach each other. So only the server needs to be reachable. gRPC is the default; `http` (WebSocket) also ran, on port 443.
- **Startup kits and certificates:** `nvflare provision` makes one kit per participant, with its private key, the root certificate and config. A client's kit is 9 KB packed. The client checks the server's identity against the name in its kit, so that name must resolve and match: a server at an unknown address, as a task would be, doesn't fit easily. `connection_security: clear` exists, but wasn't used.
- **Long-running participants as batch tasks:** the client process works in the foreground, and exits with 0 when the admin API shuts the system down, so a task ends properly. Clients retry forever if there's no server, and TES has no time limit, hence a `timeout` wrapper. They run with a read-only root file system, and as non-root (one run, with `--user 65534`), if they can write to `/tmp`.
- **Job launchers:** NVFlare has launchers that start job processes through Docker, Kubernetes and Slurm, under a long-running parent at the site. That's the proper model, with no TES in it.

How TES fits:

- A task can't ask for a port or a name. Without these, a server in a task has no address, which rules out B2 on real nodes without a relay.
- There's no field for secrets. Inputs are either inline or a URL, and both end up in task records ([H3](shortcuts.md#h3)).
- A task can't state a maximum run time, or be told to stop other than by canceling it.
- Task-to-outside networking isn't specified, so it's up to each node.

## A: NVFlare inside Conquest

[Conquest](https://github.com/anuragxxd/conquest) is a WES (1.1) in Go with Nextflow, WDL and Snakemake, which starts a runner pod per run on Kubernetes, with tasks through its internal TES, also on Kubernetes. Read at commit `900e625`. Nothing was run.

Applies to both variants:

- **Conquest's TES is internal: all tasks land in one cluster.** Submitting to proTES is [an open issue](https://github.com/elixir-cloud-aai/generic-issues/issues/28). Until that's done, this can only show a federation inside a cluster, which demonstrates plumbing and not federation.
- Conquest has no authentication in its code at this commit, and takes `workflow_url` from `github.com` only, the latter being a fine way to bring in a job.
- Pods run under the `restricted` Pod Security Standard, as non-root, which FLARE [tolerates](#how-nvflare-fits). Conquest creates no Services for its pods, so pods have IPs but no stable names, which is what the kits need.
- A local run needs a cluster, Postgres, S3 and images: 2 to 3 hours, included below. Its Helm chart and Makefile look complete.

### A1: A new workflow type

**How it works:** a new `RunAdapter` (`internal/adapter/`), registered in `cmd/conquest/main.go` and named in the service info. The runner is an image with NVFlare and the logic of the thin WES here: provision, start the server, submit tasks, submit the job.

**What's hacked:** the server in the runner pod, reached by pod IP, with kits made after that IP is known (whether a certificate for an IP works wasn't tried), or `clear` connections; or the adapter creates a Service, which changes the backend. Kits as `s3://` inputs. A workflow type that isn't one.

**What it shows the report's reader:** the planned WES of the architecture runs FL natively. Across sites only after the external TES.

**Effort:** 8 to 13 hours: 2 to 3 for the local stack, 4 to 6 for the adapter and runner, 2 to 4 for the networking.

**Risks:** a dirty branch of someone else's code, against a moving target; the owner may prefer another approach; pod-to-pod policies on the cluster.

### A2: NVFlare as workflow steps

**How it works:** a Nextflow, WDL or Snakemake workflow with one process per participant, and no change to Conquest. Processes must start at the same time, so no channels between them: the server writes its address to the shared workspace (`objectfs` or a PVC), and clients wait for it. The workflow is a repository on GitHub.

**What's hacked:** all of the above, plus a rendezvous through the file system, `clear` connections since the name isn't known up front, and no control of placement. Engines also expect processes to end on their own, so the whole thing hangs if anything goes wrong.

**What it shows the report's reader:** existing engines can carry it, with no change to the service. As a demonstration of federated learning it's thin, as all participants share a cluster and a file system, which is what federation is meant to avoid.

**Effort:** 5 to 8 hours, of which 2 to 3 for the local stack.

**Risks:** fragile; shows little until tasks can go elsewhere.

## B: A thin WES in front of NVFlare, with TES below

**How it works, in both variants:** this repository's [thin WES](design.md). It takes a run of type `NVFLARE`, makes a federation for that run alone, then schedules participants through the TES of each site, or through proTES if one is configured, and gets the job done through the FLARE admin API.

### B1: Server beside the WES

**How it works:** the FL server runs next to the WES, at one reachable address: the hub. Clients are TES tasks at the TES of their site, which the WES calls directly. They dial out. Through proTES ([stretch goal 2](index.md#goals)), the tag [`gateway.backends`](https://github.com/elixir-cloud-aai/proTES/blob/dev/docs/plugins.md#choices-of-clients) pins them to their site instead.

**What's hacked:** [all of these](shortcuts.md). The worst: kits with private keys through task records ([H3](shortcuts.md#h3)), and no authentication ([H5](shortcuts.md#h5)).

**What it shows the report's reader:** a run through standard APIs, on TES instances of different sites, with data that stays there. Which part isn't standard is plain: the server isn't scheduled through TES, and the workflow type is invented.

**Effort:** done up to the local proof. 4 to 8 more hours, for the [hub on a public machine, images in a registry, HTTPS, and a probe of the nodes](../setup/real-sites.md). Node operators' time on top.

**Risks:** nodes may not let tasks out; a node's TES may differ from Funnel (input handling, TES version; only Funnel ran here); an NVFlare upgrade changes its provisioning (it's pinned here); a public port for the hub.

### B2: Server as a TES task, too

**How it works:** as B1, with the server as one more TES task.

**What's hacked:** on top of B1: the TES of the server is configured to give its tasks a fixed name on the networks of the sites ([H6](shortcuts.md#h6)), which only works since all "sites" are on one Docker host. A real TES gives a task no reachable address: Kubernetes-based ones would need a Service and an ingress per task, and with Funnel it's up to the host.

**What it shows the report's reader:** that WES and TES carry all participants, in the literal sense, and what's missing from TES to make that work on real nodes. Valuable as a finding, not as a demonstration.

**Effort:** done locally. To make it real: 2 to 4 hours for a relay that the server task dials out to, as the clients do. That was not tried, and it's a hub again, only further down.

**Risks:** a relay adds another moving part, and ends up as B1 with more steps.

## C: Anything simpler

### C1: The simulator in one task

**How it works:** one WES run with one task, `nvflare simulator`. Should work in Conquest today with a one-process workflow, which wasn't tried. The simulator [ran](../tests/t1-simulator.md), but not as a task.

**What's hacked:** everything that matters. All data sits in one place.

**What it shows the report's reader:** nothing about federation. It's a smoke test. It'd be misleading to present it as more.

**Effort:** 1 hour.

**Risks:** being mistaken for the real thing.

### C2: A fixed NVFlare network

**How it works:** this is how NVFlare is meant to be used. One server and a client per site run for good, installed by the sites, and possibly with its own job launcher. A run is one workflow task, on any WES, that submits a job with the admin API and waits. Should work on Conquest as it is, which wasn't tried.

**What's hacked:** an admin kit in a workflow task, and one identity for all users. Otherwise it's clean, which is the point.

**What it shows the report's reader:** FL with real site control, but on the side of the architecture: TES isn't involved, and every site operates one more service.

**Effort:** 3 to 4 hours on our side. For each site, an operator has to install something long-running and keep it alive, possibly for days of coordination. That's unlikely by next week.

**Risks:** adoption, as sites have to do the work. This is the likely long-term shape, should FL become a real service.

### C3: A TES job launcher in NVFlare

**How it works:** like the launchers for Kubernetes and Slurm: long-running client parents stay at the sites, and job processes become TES tasks.

**What's hacked:** little, but it keeps a long-running parent per site, and job processes must reach it (`parent_host:internal_port` for the Slurm launcher), which means inbound to a parent from TES tasks.

**What it shows the report's reader:** an upstream-worthy integration, which uses TES for what it's good at, with the data scientist's jobs as batch work.

**Effort:** 12 to 20 hours. The Slurm launcher is a useful template, but it's a lot of code.

**Risks:** the effort, and it has C2's adoption problem. A possible proposal for later, not for the event.

### C4: FedAvg as a plain workflow

**How it works:** no FL framework. A Nextflow or Snakemake workflow, in which each round is one task per site that reads the current model and writes an update, then one aggregating task. Models travel through object storage, as with any workflow. Since tasks just end, there's no networking between participants at all, and TES and proTES fit naturally. It needs pinning tasks to sites from the engine, and Conquest's external TES to run it there.

**What's hacked:** NVFlare isn't there, so none of its privacy filters, or anything else from it. Updates sit in storage that all sites must reach. Rounds are slow (each costs a task start at each site).

**What it shows the report's reader:** federated learning with the services as they are, and nothing else. It's the batch-native answer, and the honest fallback if nodes don't let tasks out.

**Effort:** 3 to 5 hours, and it could reuse this test set. Pinning from an engine wasn't tried: it may need a plugin in the engine, or a wrapper.

**Risks:** not what was asked for: it's not NVFlare, and it's easy to get privacy wrong by hand.

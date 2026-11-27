# Report

!!! note "Results and discussion of the testbed, as of 2026-11-27"
    What ran, on what, with which evidence, and what it means. The raw rows are in [Results](results.md); what follows from them in general is in the [Gap analysis](gap-analysis.md), the [Open questions](open-questions.md) and the draft [Proposals](proposals.md). Section 5 holds draft outcomes and proposals, for further consideration: whatever is added here stays a draft, and gets finalized elsewhere. No host names of nodes, no tokens, no personal data; people are named by their roles.

## Summary

A federated learning job with NVIDIA FLARE (NVFlare) ran through a GA4GH WES, with one NVFlare client per site as a GA4GH TES task, on the TES of two ELIXIR Nodes at two organizations' infrastructure: the FI Node's TESK on Rahti, at CSC, and the CZ Node's TESK at CERIT-SC. On 2026-11-24, run `ae7742f2` ended `COMPLETE` in about 90 seconds, with the NVFlare job `FINISHED:COMPLETED`. Both TES checked the LS Login access token that the hub sent with each task. The federated model reached a holdout accuracy of 0.975, against 0.825 and 0.875 for models trained on either site's share alone: the same as in the simulator ([T1](../tests/t1-simulator.md)).

It took three milestones to get there, and a fourth sent the same run through proTES:

| Milestone | Date | Sites | Authentication at the TES | Result |
|---|---|---|---|---|
| [First run on one cluster](#first-run-on-one-cluster) | 2026-11-12 | Both sites on one TESK, in the hub's cluster on Rahti | None | `COMPLETE`, after a first `SYSTEM_ERROR` |
| [First run with tokens](#first-run-with-tokens) | 2026-11-19 | As above | Tokens sent, not checked | `COMPLETE` |
| [First multi-site run](#first-multi-site-run) | 2026-11-24 | FI Node (TESK on Rahti, CSC) and CZ Node (TESK at CERIT-SC) | LS Login tokens, checked by both | `COMPLETE`, accuracy 0.975 |
| [First run through proTES](#first-run-through-protes) | 2026-11-27 | As above, each task pinned to its site's TESK through proTES | LS Login at proTES; proTES's service token, checked by both TESKs | `COMPLETE`, accuracy 0.975 |

What it shows: TES as it is can schedule the clients of a federated job, because clients only dial out to the FL server, and the server runs beside the WES, outside TES ([option B1](../testbed/options.md#b1-server-beside-the-wes)). Whether a node can take part depends on whether its tasks get out to the hub, and on details of its TES deployment, such as its storage. What it doesn't show: a production setup. Both TES are run by the maintainers of this testbed, both are TESK, the model and data are toys, and the testbed takes every shortcut it can ([Limitations](#limitations)). ELIXIR Cloud isn't "available" for federated learning in the sense of milestone M4.5 yet: see [What this does not deliver](results.md#text-for-the-m45-report).

## Setup

What was the same in all runs on real infrastructure.

| Part | What it is | See |
|---|---|---|
| Hub | The testbed's thin WES (FastAPI), with NVFlare 2.9's FL server as a child process, deployed with the chart `charts/nvflare-wes-hub` on Rahti, the Kubernetes (OpenShift) service of CSC. The FL port, 30002, is public through a `LoadBalancer` Service; the links to kits and signing requests through an edge Route; the WES API only through `oc port-forward`. Between runs, the WES answers probes on the FL port itself | [Running it on Rahti](../setup/real-sites.md#running-it-on-rahti), [G10](gap-analysis.md#g10), [G11](gap-analysis.md#g11) |
| WES | Workflow type `NVFLARE` ([H8](../testbed/shortcuts.md#h8)), job `logreg-fedavg` for exactly two sites. One run at a time, state in memory ([H2](../testbed/shortcuts.md#h2)). Each call needs an LS Login access token for the WES's client ([H5](../testbed/shortcuts.md#h5)) | [B1](../testbed/options.md#b1-server-beside-the-wes) |
| Sites | A sites file in a Secret, read once when the hub starts: per site, the URL of its TES, the URL of its data, and a token for its TES | [Real sites](../setup/real-sites.md), [H11](../testbed/shortcuts.md#h11) |
| Client task | One task per site, in the hub's image (`elixircloud/nvflare-wes-testbed`), with 1 CPU, 1 GiB of memory and 1 GiB of disk, and the site's share of the data as its one `https` input. The task makes the site's key, has its certificate signed over a one-time link of the WES, and dials out to the FL server, with mutual TLS. A `timeout` of 30 minutes ends it if the server never ends the job | [H3](../testbed/shortcuts.md#h3), [H4](../testbed/shortcuts.md#h4), [H14](../testbed/shortcuts.md#h14) |
| Data | The synthetic test set at commit `b473b4b`: `site-1.csv` and `site-2.csv`, 40 rows each, two features and a label, each covering another part of the feature space. The holdout set stays with whoever compares the models | [The test set](../setup/real-sites.md#the-test-set), [test set](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/blob/dev/testset/README.md) |
| Model | Logistic regression in NumPy, federated averaging over 5 rounds, after NVFlare's `hello-numpy` example. `testset/evaluate.py` compares the global model with a model trained on each share alone, on the holdout set | [T1](../tests/t1-simulator.md) |
| Authentication | LS Login. The WES trusts one issuer and one client. In the multi-site run, one access token of one member of the LS Login group for compute on ELIXIR On-Cloud (EOC-Compute) served the WES and the TES of both sites; both TES accept only members of that group (and of the administrators' group) | [G5](gap-analysis.md#g5), [G6](gap-analysis.md#g6) |

Before a site joins a run, a probe task at its TES checks what a client needs: whether it gets out to the hub's FL port, and on 443; whether it can download an input; whether `env` is passed; its user and group; and whether `/tmp` and `/` are writable ([Probing a node](../setup/real-sites.md#probing-a-node)).

## Milestones

### Local runs

Before any real infrastructure, on laptops, 2026-11-04 and 2026-11-11: two local Funnel instances as sites, directly and through proTES, with mutual TLS between participants. The federated model reached 0.975, against 0.825 and 0.875 for the sites alone, in the simulator ([T1](../tests/t1-simulator.md)) and through WES and TES ([T2](../tests/t2-wes-to-tes.md)). The server also ran as a TES task, but only on a Funnel hacked to give it a fixed name on the networks of all sites ([T5](../tests/t5-server-task.md), [H6](../testbed/shortcuts.md#h6)). See [Local runs](../tests/index.md#local-runs); CI runs most of them on every pull request.

### First run on one cluster

**What ran.** 2026-11-12: the hub on Rahti, for the first time, and both sites as tasks on one TESK (chart 0.3.0, tesk-api 1.2.0) without authentication, in the same cluster. Again on 2026-11-16, as a dress rehearsal for the event.

**Evidence.** [Results](results.md), rows of 2026-11-12 and 2026-11-16 (run `6f2f6bd9`); [#7](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/7), [#42](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/pull/42); [What differed on Rahti](../setup/real-sites.md#what-differed-on-rahti).

**Result.** The first run ended `SYSTEM_ERROR` after the start timeout, and no site joined: a listener left behind in the hub's pod for the probe held the FL port, and NVFlare's FL server started without it, only logging that ([G9](gap-analysis.md#g9)). After a restart of the pod, the run ended `COMPLETE`, with the NVFlare job `FINISHED:COMPLETED`. Runs now fail at once when the FL port is taken ([#41](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/pull/41)), and the WES answers probes between runs, so that no listener is needed ([#47](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/pull/47)). The install also found two limits of Rahti that other OpenShift clusters may share: no seccomp profile `RuntimeDefault` ([G7](gap-analysis.md#g7)), and a CPU limit of at most 5 times the request ([G8](gap-analysis.md#g8)). Accuracies and start times of tasks weren't recorded.

**What it means.** The pieces fit on a real cluster: the chart, the public FL port, the kits behind a Route, and TESK running the hub's image as an arbitrary user. But the tasks reached the FL port from inside the hub's own cluster (hairpin), so this says nothing about other nodes.

### First run with tokens

**What ran.** 2026-11-19, run `9cfe6bb4`: as above, with the hub sending an LS Login access token to the TES for each site, from its sites file.

**Evidence.** [Results](results.md), rows of 2026-11-19; [generic-issues#110](https://github.com/elixir-cloud-aai/generic-issues/issues/110).

**Result.** `COMPLETE` in about 90 seconds, NVFlare job `FINISHED:COMPLETED`. That TESK ran without authentication, and ignored the tokens: this showed that the hub sends them and that a TES without authentication tolerates them, not that a TES that checks tokens accepts the hub's tasks.

The first run on a TES that checks tokens had both sites on the FI Node's TESK, after it started to require LS Login tokens ([generic-issues#35](https://github.com/elixir-cloud-aai/generic-issues/issues/35)). On 2026-11-24, run `1eae12bf` ended `SYSTEM_ERROR`, as the client of site 1 never joined. The TESK accepted the token and created the task, but the task's executor couldn't start: the task's volume, a Cinder volume on Rahti that only one node can attach at a time (`ReadWriteOnce`), was attached to the node of the task's filer, and the executor was scheduled on another node. Kubernetes reported `Multi-Attach`, and OpenStack refused the attachment with `400` ("already attached"). That's a limitation of TESK on that storage, not of the testbed: see [Limitations of the sites](#of-the-sites) and [Suggestions for TES](#for-tes).

**What it means.** The hub's tokens per site work as documented ([Tokens for the TES of the sites](../setup/real-sites.md#tokens-for-the-tes-of-the-sites)). Whether a run gets through depends on the TES's deployment as much as on the testbed.

### First multi-site run

**What ran.** 2026-11-24, at about 03:34 CET, run `ae7742f2`, with site 1 on the FI Node's TESK, on Rahti at CSC (chart 0.4.0, tesk-api 2.0.0, LS Login tokens required), and site 2 on the CZ Node's TESK at CERIT-SC, which the maintainer deployed in a namespace of its own there (TESK from its development heads after tesk-api 2.0.0, Pod Security `restricted`, task volumes on CephFS, LS Login tokens required). Both TES got the same LS Login access token, of one member of EOC-Compute. Data at commit `b473b4b`.

**Evidence.** Probes of both sites, the same night, posted on [#3](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/3#issuecomment-7120183508); [Results](results.md), rows of 2026-11-24.

| What | FI Node (site 1) | CZ Node (site 2) |
|---|---|---|
| TES | TESK, chart 0.4.0, tesk-api 2.0.0, at CSC | TESK, development heads after tesk-api 2.0.0, at CERIT-SC |
| Operated by | The testbed's maintainers, on Rahti | The maintainer, in a namespace that the CZ Node's operator provided |
| Probe | `COMPLETE`. FL port 30002 `open`, 443 timeout (not needed), input downloaded, `env` passed, uid 1002390000 and gid 0 (assigned by OpenShift), `/tmp` writable, `/` not | `COMPLETE`. FL port 30002 `open`, 443 timeout (not needed), input downloaded, `env` passed, uid 100, `/tmp` writable, `/` not |
| What it took to get out | Nothing: tasks reach the hub's FL port (within the same cluster, hairpin) | Nothing: tasks reach the hub's FL port across organizations |
| What else it took | – | `fsGroup` 100 on the filer and executor pods, as the CephFS volumes of tasks are owned by root |
| Client task | Started within 1 s of its creation, ran for about 71 s, `COMPLETE` | Started within 1 s of its creation, ran for about 71 s, `COMPLETE` |

| Run `ae7742f2` | |
|---|---|
| `QUEUED` | 03:34:21 CET |
| `RUNNING` | 03:34:31 CET |
| `COMPLETE` | 03:35:53 CET, about 92 s after `QUEUED` |
| NVFlare job | `FINISHED:COMPLETED` |
| Holdout accuracy | Federated 0.975; site 1 alone 0.825; site 2 alone 0.875 |

Port 443 timed out at both nodes, as the hub's address for the FL port publishes only that port: the probe's 443 says nothing about whether these nodes let tasks out on 443.

**Result.** All of [#10](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/10)'s criteria of success are met: the run ended `COMPLETE`, the NVFlare job `FINISHED:COMPLETED`, and the holdout accuracy is that of T1. Each node is recorded as [T8](../tests/t8-real-sites.md) asks, without host names.

**What it means.** A WES can run an NVFlare job over the TES of two Nodes, at two organizations' infrastructure, with the user's LS Login token checked by each TES, and with nothing inbound at either site. Tasks started at once on both nodes, well within the WES's start timeout of 3 minutes.

### First run through proTES

**What ran.** 2026-11-27, at 16:11 UTC, run `607ecdff` ([#18](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/18)). The run of [First multi-site run](#first-multi-site-run), with both client tasks sent to proTES 0.7.0 at `https://gateway-tes.elixir-on.cloud`, each pinned to its site's TESK by URL (`gateway.backends`), which proTES called with a service token of its own client. The hub (revision 8 of its release on Rahti, image `sha-55309b5`) called proTES with one LS Login access token of a member of EOC-Compute.

**Evidence.** Probes of both sites through proTES, the same day; [Results](results.md), rows of 2026-11-27.

| What | FI Node (site 1) | CZ Node (site 2) |
|---|---|---|
| Probe through proTES | `COMPLETE`. FL port 30002 `open`, 443 timeout (not needed), input downloaded, `env` passed, uid 1002390000 and gid 0, `/tmp` writable, `/` not | Ran as on 2026-11-24 (executor's log at the node: 30002 `open`, 443 timeout, input downloaded, `env` passed, uid 100 and gid 0, `/tmp` writable, `/` not), but stored by proTES as `SYSTEM_ERROR`, without logs: a race, below |
| Client task | Ran at `https://tesk.rahtiapp.fi`, as pinned, `COMPLETE` | Ran at `https://tesk.dyn.cloud.e-infra.cz`, as pinned, `COMPLETE` |

| Run `607ecdff` | |
|---|---|
| `QUEUED` | 16:11:30 UTC |
| `COMPLETE` | 16:13:02 UTC, about 92 s after `QUEUED`, as the direct run |
| NVFlare job | `FINISHED:COMPLETED` |
| Holdout accuracy | Federated 0.975; site 1 alone 0.825; site 2 alone 0.875 |

The times that proTES stores for a task aren't the task's: proTES sets its start when it receives the task and its end when it has forwarded it, less than 1 s apart, and doesn't take the times of the TES ([protes#528](https://github.com/elixir-cloud-aai/protes/issues/528)). This section gives none of them.

**The race.** The CZ probe's task finished at the node: its executor logged its findings, the taskmaster exited with 0 and its Kubernetes job was `Complete`. proTES polled the CZ TESK in the same second as that job finished. Kubernetes briefly reports a job that has just finished with neither an active nor a succeeded pod, and tesk-api's `TaskStateResolver` returns `SYSTEM_ERROR` for that ([tesk-api#233](https://github.com/elixir-cloud-aai/tesk-api/issues/233)). proTES's follow-up request for the full task, 0.3 s later, disagreed, but proTES kept the first final state and dropped the logs ([protes#527](https://github.com/elixir-cloud-aai/protes/issues/527)). Any task at either TESK can hit this, client tasks of a run included; this run didn't.

**Result.** The run met the criteria of [First multi-site run](#first-multi-site-run) through proTES: `COMPLETE`, the NVFlare job `FINISHED:COMPLETED`, the accuracy of T1, and each task at its site's TESK.

**What it means.** A WES can send the tasks of a federated job to a TES gateway and pin each one to its site, without any change to proTES, and the TES of each site can check the gateway's own token rather than the user's. The gateway adds a step that can go wrong, though: it keeps its own copy of a task's state, which can be wrong when it polls at the wrong moment, and its own task times. What a plugin of proTES for sites would add, and what it can't do: [A site plugin for proTES](protes-plugin.md).

### The DE Node

The DE Node took part in the probes only. On 2026-11-21, two TES deployments there accepted an LS Login access token. A Funnel ran the probe, but its tasks got out to the hub neither on the FL port nor on 443, and the download of the input failed too; a TESK failed before the probe ran, when its taskmaster's own access to Kubernetes was refused ([#3](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/3#issuecomment-7063257957), [Results](results.md)). The DE Node can join once its tasks reach the hub and the download of the input works: that's a follow-up of ELIXIR On-Cloud, not a milestone of this testbed.

## Discussion

**TES is enough for the clients, not for the server.** The clients of a federated job fit TES as it is: a batch task with one input, which dials out and ends with the job. The FL server doesn't: TES has no service-like tasks, so it runs beside the WES, at a hub with a public port and a fixed name ([G1](gap-analysis.md#g1), [Service-like tasks](proposals.md#service-like-tasks)). That puts the hub, and whoever runs it, at the center of every run: one public port, one run at a time ([G12](gap-analysis.md#g12)).

**Egress decides whether a node can take part.** No inbound connection was needed at any site: what decided was whether a task gets out to the hub. It did at the FI and CZ Nodes, on the FL port 30002, and didn't at the DE Node, on neither 30002 nor 443. A node's policy on egress is in nothing that a TES says about itself: only a probe finds it out ([G11](gap-analysis.md#g11)). Rahti only exposes ports between 30000 and 35000 through a `LoadBalancer`, which nodes may block more often than 443 ([T7](../tests/t7-port-443.md) ran locally only).

**The TES's deployment matters as much as its API.** Both sites ran TESK, and both needed something of their storage: at Rahti, a `ReadWriteOnce` volume that the filer and the executor of a task can only share on one node, which failed one run; at CERIT-SC, an `fsGroup` for root-owned CephFS volumes. Neither shows in anything a TES says about itself, and neither is something a WES can work around ([G13](gap-analysis.md#g13), [G14](gap-analysis.md#g14)). The same image ran as an arbitrary user (Rahti) and as uid 100 under Pod Security `restricted` (CERIT-SC) without changes, as it runs as any user, with `HOME=/tmp`.

**One token for everything works, and is the wrong model.** One user's access token served the WES and both TES, because both TES trust the same issuer and the same group. Each task is then the user's own, at every site, which is what an owner-only TES needs to show the WES its tasks. But the hub holds that user's token for the run, the token expires after about an hour with no renewal set up on Rahti, and every site sees the same identity. The proper way is a token per site, exchanged from the caller's own, as the [token exchange testbed](https://github.com/elixir-cloud-aai/token-exchange-flow-testbed) sets out ([G5](gap-analysis.md#g5), [H25](../testbed/shortcuts.md#h25)).

**Fast, at this size.** Tasks started within a second, and the run took about 90 seconds: start-up times and the WES's timeouts weren't an issue. Neither is known for bigger images, data or models, or for nodes with queues.

**The accuracy is a check, not a result.** The model and data are made so that a federated model beats the sites alone: matching T1 means that the job ran as in the simulator, across real sites, not that anything was learned.

## Limitations

### Of the test cases

- **A toy model and toy data.** Logistic regression over two features, 40 synthetic rows per site, 5 rounds. Nothing about performance, scale or the value of a model follows ([Scope](../testbed/index.md#scope)).
- **Two sites, one job.** The job takes exactly two sites (`min_clients` 2). Jobs for three and four sites exist and run in CI ([#54](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/pull/54)), not on real nodes. Any lost site fails the run, and sites don't rejoin ([H18](../testbed/shortcuts.md#h18)).
- **Short runs.** About 90 seconds, well within the lifetime of one access token. Renewal during a run, long rounds and the 30-minute `timeout` of the clients ([H14](../testbed/shortcuts.md#h14)) weren't put to the test.
- **Two multi-site runs.** Run `ae7742f2`, directly, and run `607ecdff`, through proTES, passed once each; they aren't a series.
- **No one-site runs.** The plan of [#10](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/10) called for a run with one site per Node (`min_clients` 1) before the run with all sites. The probes at each Node took their place, and the run with both sites passed at once.
- **Central evaluation.** The models of one site alone are trained by `evaluate.py`, from the shares of the test set, not at the sites ([H12](../testbed/shortcuts.md#h12)).

### Of the sites

- **Both are ours.** The FI Node's TESK is run by the testbed's maintainers, on Rahti; the CZ Node's TESK was deployed by the maintainer in a namespace that the CZ Node's operator provided. The run crossed two organizations' infrastructure and networks, but no partner operated a TES, decided on a job, or answered the [questions for operators](../setup/real-sites.md#what-to-ask-node-operators).
- **The hub and site 1 share a cluster.** The FI Node's tasks reached the FL port from inside Rahti (hairpin); only the CZ Node's tasks came from outside.
- **The DE Node couldn't join.** Its tasks have no way out to the hub ([The DE Node](#the-de-node)).
- **Storage at Rahti.** TESK's task volumes on Rahti are `ReadWriteOnce` Cinder volumes. When the scheduler puts a task's executor on another node than its filer, the executor can't start (`Multi-Attach`, then OpenStack's `400` "already attached"), and the run fails: run `1eae12bf` did, on 2026-11-24, while site 1's task in run `ae7742f2` got through. It depends on where pods land, so any run with the FI Node's TESK may fail this way ([G13](gap-analysis.md#g13)).

### Same TES implementation

Both sites ran TESK, of two versions, in two Kubernetes clusters with different storage and pod security. Funnel ran the local tests, and a Funnel at the DE Node ran the probe, but no Funnel, Poiesis or other TES took part in a run on real infrastructure. Whether the hub's tasks run the same on another implementation, with its own handling of inputs, `env`, users and tokens, is untested there.

### Shortcuts, workarounds and simplifications

What the runs relied on, beyond the general [shortcuts and hacks](../testbed/shortcuts.md):

| What | Where it shows | Proper way |
|---|---|---|
| One user's access token for the WES and all sites, in the sites file | Sites file; [G5](gap-analysis.md#g5) | A token per site, exchanged from the caller's ([H25](../testbed/shortcuts.md#h25)) |
| No renewal: the key `token` is never renewed, and an access token lives about an hour, so one run per token, renewed by hand | [Tokens for the TES of the sites](../setup/real-sites.md#tokens-for-the-tes-of-the-sites) | `token_file` from a Secret, or `oauth`, which the hub supports ([#39](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/pull/39)) but which isn't set up on Rahti |
| A sites file written by hand, read once at start: changing sites or tokens takes a new Secret and a restart of the hub, which forgets its runs | [H2](../testbed/shortcuts.md#h2), [H11](../testbed/shortcuts.md#h11) | Sites from a registry, looked up per run |
| The FL port through a `LoadBalancer` Service, on a high port, 30002 | [G11](gap-analysis.md#g11) | A long-running FL service at a known address, or service-like TES tasks ([G1](gap-analysis.md#g1)) |
| The WES answers probes on the FL port between runs | [G10](gap-analysis.md#g10) | A probe that a TES or a registry offers, or an FL service that's always up |
| The WES API only through `oc port-forward`, by the maintainer | [Running it on Rahti](../setup/real-sites.md#running-it-on-rahti) | A public WES behind a gateway, with rate limits ([H23](../testbed/shortcuts.md#h23)) |
| Owner-only TES: each TESK shows a task only to the user who created it, so the start times of tasks were read at each TES with the run's token | This report | Task records in the WES's run log ([H17](../testbed/shortcuts.md#h17)) |
| A one-time link for the site's certificate in the command of its task | [H3](../testbed/shortcuts.md#h3), [G3](gap-analysis.md#g3) | [Secrets for tasks](proposals.md#secrets-for-tasks) |
| Public data URLs, chosen by the WES; no job approval at the sites | [H13](../testbed/shortcuts.md#h13), [H16](../testbed/shortcuts.md#h16) | Data that only resolves at its site; NVFlare's site policies |
| Every caller is NVFlare's `lead`, with tokens of one trusted issuer | [H5](../testbed/shortcuts.md#h5), [G6](gap-analysis.md#g6) | Roles and studies from the caller's groups |
| An unsigned image, with version ranges | [H20](../testbed/shortcuts.md#h20) | Locked, scanned and signed images |
| `fsGroup` 100 on TESK's filer and executor pods at the CZ Node, in its deployment | [G14](gap-analysis.md#g14) | Documented for TESK ([TESK#341](https://github.com/elixir-cloud-aai/TESK/issues/341), [tesk-core#167](https://github.com/elixir-cloud-aai/tesk-core/issues/167)) |

## Suggestions

### For WES

For this WES, and for a WES of ELIXIR On-Cloud that runs federated jobs, such as proWES:

- **The caller's token, exchanged per site.** Get a token for the TES of each site by token exchange from the caller's own, rather than holding one user's token for all ([H25](../testbed/shortcuts.md#h25); [prowes#198](https://github.com/elixir-cloud-aai/prowes/issues/198), [protes#501](https://github.com/elixir-cloud-aai/protes/issues/501)). Until then, renew tokens without restarts (`token_file` or `oauth`, [#39](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/pull/39)).
- **Sites per run, not per deployment.** Take the sites of a run from a registry ([Cloud Registry](https://github.com/elixir-cloud-aai/cloud-registry)), or route through proTES, pinned to each site ([#18](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/18), [G4](gap-analysis.md#g4)), so that changing sites takes no restart.
- **Probe before the run.** Run the probe at each site before submitting a run's tasks, and refuse the run, with a reason, when a site can't reach the FL server, rather than waiting for the start timeout.
- **Show the tasks.** Put the TES records of a run's tasks, their states, start times and system logs, into the run log, in the fields of the WES specification ([H17](../testbed/shortcuts.md#h17)): with owner-only TES, the WES is where the user sees them.
- **More than one run.** A queue and persistent state ([G12](gap-analysis.md#g12)).

### For proTES

- **Poll again before a final state.** Keep a final state of a task only when a second poll of the TES agrees, and keep the TES's logs with it ([First run through proTES](#first-run-through-protes), [protes#527](https://github.com/elixir-cloud-aai/protes/issues/527)).
- **The TES's times.** Store the start and end times that the TES reports for a task, not when proTES received and forwarded it ([protes#528](https://github.com/elixir-cloud-aai/protes/issues/528)).
- **Sites, not TES instances.** [A site plugin for proTES](protes-plugin.md).

### For TES

For TES, the specification, and for TESK in particular:

- **Keep a task's pods on one node, or use shared storage.** TESK's filer and executors share a volume. With storage that one node attaches at a time (`ReadWriteOnce`), its executors should be scheduled on the filer's node, for example by node affinity, or the deployment should use a storage class with `ReadWriteMany`. TESK's deployment guide should say which storage it needs ([G13](gap-analysis.md#g13)). No issue exists for this yet.
- **Say what tasks may reach.** Node operators should document, and a TES could say in its service info, what its tasks may connect to: which ports, through which proxy ([Proposals](proposals.md), [G11](gap-analysis.md#g11)). A WES then knows before it submits.
- **No error for a job that has just finished.** tesk-api reports `SYSTEM_ERROR` for a task whose Kubernetes job briefly shows neither an active nor a succeeded pod, as a job does right after it finishes ([First run through proTES](#first-run-through-protes), [tesk-api#233](https://github.com/elixir-cloud-aai/tesk-api/issues/233)).
- **Report why a task failed.** Put reasons from the backend, such as a volume that can't be attached, into the task's `system_logs`, so that a WES and its user see them without access to the cluster.
- **Tokens.** Accept tokens exchanged for the TES, with an audience, so that a WES can act for its caller without holding the caller's own token ([G5](gap-analysis.md#g5)).
- **Pinning by site.** Pin tasks to a site by a property of the site or of its data, not by URL ([Pinning tasks by a property of a site](proposals.md#pinning-tasks-by-a-property-of-a-site)).
- **What federated jobs need beyond that:** [service-like tasks](proposals.md#service-like-tasks), [time limits](proposals.md#time-limits-for-tasks) and [secrets for tasks](proposals.md#secrets-for-tasks), in the draft [Proposals](proposals.md).

## Outlook

- **A third site, or a second implementation.** The jobs for three and four sites are ready ([Running with n sites](../setup/real-sites.md#running-with-n-sites)). A third Node, or a site on another TES implementation, such as a Funnel, would test what two TESK can't. The DE Node can join once its tasks reach the hub and the download of the input works.
- **A site plugin for proTES.** Name sites rather than TES instances, from a registry ([A site plugin for proTES](protes-plugin.md)).
- **Into ELIXIR On-Cloud.** A permanent deployment, with more sites, implementations and models, proper authentication, and integration with proWES and Conquest, in place of a testbed that takes every shortcut.

# Proposals

!!! note "Draft; nothing posted"
    Section 5 holds draft outcomes and proposals, for further consideration, and only what test results support. These come from the local runs and from the two dress rehearsals on Rahti; the run with two or more sites ([#10](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/10)) may add to them. Nothing is posted anywhere without the maintainer's OK. Whatever is added here stays a draft: it gets finalized elsewhere.

Each proposal links the [gaps](gap-analysis.md) it closes.

## GA4GH Federated Analysis Work Stream, and the Cloud AI/ML Working Group

What TES lacks for participants of a federated job, against [TES 1.1](https://github.com/ga4gh/task-execution-schemas). Field names below are sketches in the style of TES (snake case), to make each proposal concrete: their shape is for the Work Stream to decide.

Each proposal names the issues and pull requests of the TES repository on the same topic, as of 2026-11-21. Check them again before any of this goes out, and refer to them rather than open a duplicate.

| Proposal | Gaps closed | Related in TES | Status |
|---|---|---|---|
| [Service-like tasks](#service-like-tasks) | [G1](gap-analysis.md#g1) | [#22](https://github.com/ga4gh/task-execution-schemas/pull/22) and [#96](https://github.com/ga4gh/task-execution-schemas/pull/96) (ports, added and removed in 2017), [#191](https://github.com/ga4gh/task-execution-schemas/issues/191), [#237](https://github.com/ga4gh/task-execution-schemas/issues/237) | Draft, not posted |
| [Time limits for tasks](#time-limits-for-tasks) | [G2](gap-analysis.md#g2) | [#213](https://github.com/ga4gh/task-execution-schemas/issues/213), [#141](https://github.com/ga4gh/task-execution-schemas/pull/141) | Draft, not posted |
| [Secrets for tasks](#secrets-for-tasks) | [G3](gap-analysis.md#g3) | [#167](https://github.com/ga4gh/task-execution-schemas/issues/167), [#169](https://github.com/ga4gh/task-execution-schemas/issues/169) | Draft, not posted |
| [Pinning tasks by a property of a site](#pinning-tasks-by-a-property-of-a-site) | [G4](gap-analysis.md#g4) | [#188](https://github.com/ga4gh/task-execution-schemas/issues/188), [#206](https://github.com/ga4gh/task-execution-schemas/issues/206) and [#244](https://github.com/ga4gh/task-execution-schemas/pull/244) (capabilities) | Draft, not posted |

Not every federated job needs all four. A plain FedAvg run ([C4](../testbed/options.md#c4-fedavg-as-a-plain-workflow), [T10](../tests/t10-fedavg.md)) works with TES as it is: its tasks just end, with no network between participants and no secret in any record. It still needs its tasks pinned to their sites, and the WES still ends rounds that don't finish with timeouts of its own. Service-like tasks and secrets are what a framework needs whose participants talk to each other while they run, as NVFlare's do ([Fit with TES and WES](../background/requirements.md#fit-with-tes-and-wes)).

### Service-like tasks

**Problem.** A TES task is batch: it can't ask for an address, a name or a port that others reach. Federated learning needs one participant that others dial, the FL server. In this testbed, it runs outside TES, beside the WES, at a hub with a public port and a fixed name ([B1](../testbed/options.md#b1-server-beside-the-wes)). With the FL server as a task, the run passed only on a Funnel hacked to give its executors a fixed name on the networks of all sites ([T5](../tests/t5-server-task.md), 8/8 checks on 2026-11-04 and 10/10 on 2026-11-11; [H6](../testbed/shortcuts.md#h6)). NVFlare itself doesn't mind: a server in a task works, if it has a name that its clients know. The clients need nothing of the kind: they only dial out, and nothing reaches into a site ([T3](../tests/t3-isolation.md)), on port 443 as well ([T7](../tests/t7-port-443.md)).

**Proposal.** A task may declare endpoints, each with a name, a port and a protocol, for example `endpoints: [{"name": "fl-server", "port": 8002, "protocol": "tcp"}]`. Once the task is running, its record holds the address at which each endpoint is reached, and from where: within the TES, or from outside. A TES that can't offer endpoints refuses the task when it's created, rather than running it unreachable; its service info says whether it offers them, and of which reach. A service-like task also needs a [time limit](#time-limits-for-tasks), so that it ends with the job.

**What it changes here.** The FL server becomes a task at a site, or at a TES of the federation, like the clients: the hub needs no public port of its own, and a fixed port no longer limits runs to one at a time. Concurrent runs also need the WES to drop its single run slot, a separate change ([G12](gap-analysis.md#g12)). Clients still dial out to the server's address, so sites need nothing inbound.

**Related in TES.** TES had ports once: [#22](https://github.com/ga4gh/task-execution-schemas/pull/22) added bindings between the ports of an executor's container and its host, and the host's IP address in the executor's logs, so that clients could find a running task; [#96](https://github.com/ga4gh/task-execution-schemas/pull/96) removed them in 2017, after a request to explain what they were for ([#63](https://github.com/ga4gh/task-execution-schemas/issues/63)). They were bindings on one host, with no name and nothing to say from where the address is reached. [#191](https://github.com/ga4gh/task-execution-schemas/issues/191) asks to attach a task to named networks, Docker's notion of what H6 hacks. [#237](https://github.com/ga4gh/task-execution-schemas/issues/237) names binding ports among the risks of tasks that TES leaves undefined: a TES that offers endpoints has to say what else a task may open.

**Open points.** Whether endpoints reachable from other sites are something a TES at a site would offer at all; T5 asks node operators exactly that ([Open questions](open-questions.md)). Names and TLS: the FL server's certificate holds its name, so the name must be known before the task runs, or certificates must be issued once the address is.

### Time limits for tasks

**Problem.** A task can't state how long it may run. Here, each client runs under a `timeout` of 30 minutes, in the image, and the WES has constants of its own ([H14](../testbed/shortcuts.md#h14)); without the wrapper, a client that loses the server retries forever, and holds its slot at the site. A plain FedAvg run needs the same: the WES fails a round that doesn't end in time, and cancels its tasks ([T10](../tests/t10-fedavg.md)). No backend enforces the limit, and a site can't see it before it admits a task.

**Proposal.** An optional maximum run time per task, for example `resources.max_runtime_seconds`, which the TES enforces: it ends the task when the time is up, with a state or a log entry that says so. A TES may refuse a task that asks for more than it allows, and may say its maximum in its service info.

**What it changes here.** The limit is a backstop, not the way a run ends: when the job ends, the WES should still cancel its participants with TES's existing cancel call, so that they free their slots at once ([H15](../testbed/shortcuts.md#h15)). Cancel does that today when a site is lost: the WES cancels the other clients, and no task is left behind ([T6](../tests/t6-site-loss.md)). The limit covers what that misses, such as a WES that fails before it cancels. Sites also know up front how long a federated task may hold resources, and the wrapper goes away.

**Related in TES.** [#213](https://github.com/ga4gh/task-execution-schemas/issues/213) asks for a time limit on tasks or executors. [#141](https://github.com/ga4gh/task-execution-schemas/pull/141), an open pull request of 2020 marked as work in progress, adds `resources.max_time`, a requested maximum wall time in hours that a queuing engine "may" use to set the priority of a task. This proposal asks for more than a hint: a limit that the TES enforces, and says it enforces, as a federated task that outlives its job holds its slot at the site.

### Secrets for tasks

**Problem.** TES has no way to hand a secret to a task that keeps it out of task records and logs: inputs, `env` and command lines are all part of the record, and visible to whoever can read it, at the TES and at any gateway in front of it. Here, a site's task gets a one-time link to have its certificate signing request signed, in the command of its executor ([#30](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/pull/30), [H3](../testbed/shortcuts.md#h3)). Whoever reads the record before the task uses the link can get a certificate of that site for the run. Before #30, the inputs held whole startup kits, with private keys; since then, [T2](../tests/t2-wes-to-tes.md) checks that no kit is among the inputs, and that the links are dead after the run.

**Proposal.** A task may name secrets that the TES hands to executors, for example as files or variables, without storing their values in the task's record, and without returning them on `GET` of the task: the record shows only their names. Values come either with the request, and are dropped once handed over, or as references to a secret store that the TES trusts. Neither the TES nor a gateway in front of it writes their values to any log, including logs of requests; a gateway passes them on in the same way.

**What it changes here.** The one-time link, or any other credential of a run, leaves the task records. It doesn't solve how the WES authenticates to the TES of each site ([G5](gap-analysis.md#g5)), which is about the caller's credentials, not the task's. Nor does it cover what a task returns: a plain FedAvg run needs no secret, but leaves the model and each site's update in the records of the sites' TES ([H24](../testbed/shortcuts.md#h24)).

**Related in TES.** Two open issues ask for secrets that the TES itself uses, not the task: credentials to pull images from private registries ([#167](https://github.com/ga4gh/task-execution-schemas/issues/167), asked for by ELIXIR nodes) and to stage inputs and outputs ([#169](https://github.com/ga4gh/task-execution-schemas/issues/169)). They need the same thing, a value that reaches where it's used and no record or log on the way, and one mechanism could serve all three.

### Pinning tasks by a property of a site

**Problem.** A task is pinned to a site by the URL of a TES: directly, or through proTES with the tag `gateway.backends`, which also takes proTES's identifier of the TES (the site's `backend`), a static map all the same ([T4](../tests/t4-protes.md), [H11](../testbed/shortcuts.md#h11)). A run is tied to addresses, and nothing says which site holds which data. A federated job needs exactly one participant at each site that holds a share of the data, wherever that site's TES is. With three or four sites, each must get a different share of the test set, or the expected accuracies don't hold ([Running with n sites](../setup/real-sites.md#running-with-n-sites)): which share is where is in the sites file of the hub, not in anything a site says. A plain FedAvg run pins its tasks from the same sites file ([T10](../tests/t10-fedavg.md)).

**Proposal.** A task may state constraints on where it runs by properties of a site, or of the data it needs, rather than by an address: for example, the organization that runs a TES, as in the `organization` of its GA4GH service info, or a data identifier that only resolves at its site, as with DRS. A gateway routes the task to a TES that meets them, or refuses it when none does; a TES refuses a task whose constraints it doesn't meet. TES 1.1's `resources.zones` and `tags` don't carry this: zones are within a TES, and tags have no agreed meaning. Nor does `resources.backend_parameters`, which is for the settings of a backend.

**What it changes here.** The WES's static map of sites becomes a lookup, in a registry such as the [Cloud Registry](https://github.com/elixir-cloud-aai/cloud-registry), and a site can move its TES without changing any sites file.

**Related in TES.** [#188](https://github.com/ga4gh/task-execution-schemas/issues/188) asks how a TES describes what it can do, so that a WES can choose among TES instances for a task: the routing half of this proposal. [#206](https://github.com/ga4gh/task-execution-schemas/issues/206) asks for a capabilities endpoint, which the open pull request [#244](https://github.com/ga4gh/task-execution-schemas/pull/244) adds. Properties of a site, such as who runs it and which data it holds, would fit there, or in service info, as long as a gateway can match a task against them.

## ELIXIR On-Cloud

| Proposal | Gaps closed | Status |
|---|---|---|
| | | |

## NVFlare

| Proposal | Gaps closed | Status |
|---|---|---|
| | | |

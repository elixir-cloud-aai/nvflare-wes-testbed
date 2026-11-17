# Proposals

!!! note "Draft; nothing posted"
    Section 5 holds draft outcomes and proposals, for further consideration, and only what test results support. These come from the local runs and from the two dress rehearsals on Rahti; the run with two or more sites ([#10](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/10)) may add to them. Nothing is posted anywhere without the maintainer's OK. Whatever is added here stays a draft: it gets finalized elsewhere.

Each proposal links the [gaps](gap-analysis.md) it closes.

## GA4GH Federated Analysis Work Stream, and the Cloud AI/ML Working Group

What TES lacks for participants of a federated job, against [TES 1.1](https://github.com/ga4gh/task-execution-schemas). Field names below are sketches in the style of TES (snake case), to make each proposal concrete: their shape is for the Work Stream to decide. Before any of this goes out, check the open issues and pull requests of the TES repository for proposals on the same topics, and refer to them.

| Proposal | Gaps closed | Status |
|---|---|---|
| [Service-like tasks](#service-like-tasks) | [G1](gap-analysis.md#g1) | Draft, not posted |
| [Time limits for tasks](#time-limits-for-tasks) | [G2](gap-analysis.md#g2) | Draft, not posted |
| [Secrets for tasks](#secrets-for-tasks) | [G3](gap-analysis.md#g3) | Draft, not posted |
| [Pinning tasks by a property of a site](#pinning-tasks-by-a-property-of-a-site) | [G4](gap-analysis.md#g4) | Draft, not posted |

### Service-like tasks

**Problem.** A TES task is batch: it can't ask for an address, a name or a port that others reach. Federated learning needs one participant that others dial, the FL server. In this testbed, it runs outside TES, beside the WES, at a hub with a public port and a fixed name ([B1](../testbed/options.md#b1-server-beside-the-wes)). With the FL server as a task, the run passed only on a Funnel hacked to give its executors a fixed name on the networks of all sites ([T5](../tests/t5-server-task.md), [H6](../testbed/shortcuts.md#h6)).

**Proposal.** A task may declare endpoints, each with a name, a port and a protocol, for example `endpoints: [{"name": "fl-server", "port": 8002, "protocol": "tcp"}]`. Once the task is running, its record holds the address at which each endpoint is reached, and from where: within the TES, or from outside. A TES that can't offer endpoints refuses the task when it's created, rather than running it unreachable; its service info says whether it offers them, and of which reach. A service-like task also needs a [time limit](#time-limits-for-tasks), so that it ends with the job.

**What it changes here.** The FL server becomes a task at a site, or at a TES of the federation, like the clients: the hub needs no public port of its own, and runs are no longer limited to one at a time by a fixed port ([G12](gap-analysis.md#g12)). Clients still dial out to the server's address, so sites need nothing inbound.

**Open points.** Whether endpoints reachable from other sites are something a TES at a site would offer at all; T5 asks node operators exactly that ([Open questions](open-questions.md)). Names and TLS: the FL server's certificate holds its name, so the name must be known before the task runs, or certificates must be issued once the address is.

### Time limits for tasks

**Problem.** A task can't state how long it may run. Here, each client runs under a `timeout` of 30 minutes, in the image, and the WES has constants of its own ([H14](../testbed/shortcuts.md#h14)); without the wrapper, a client that loses the server retries forever, and holds its slot at the site. No backend enforces the limit, and a site can't see it before it admits a task.

**Proposal.** An optional maximum run time per task, for example `resources.max_runtime_seconds`, which the TES enforces: it ends the task when the time is up, with a state or a log entry that says so. A TES may refuse a task that asks for more than it allows, and may say its maximum in its service info.

**What it changes here.** Participants end with the job even when they fail to notice that it ended, sites know up front how long a federated task may hold resources, and the wrapper goes away.

### Secrets for tasks

**Problem.** TES has no way to hand a secret to a task that keeps it out of task records and logs: inputs, `env` and command lines are all part of the record, and visible to whoever can read it, at the TES and at any gateway in front of it. Here, a site's task gets a one-time link to have its certificate signing request signed, in its inputs ([#30](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/pull/30), [H3](../testbed/shortcuts.md#h3)). Whoever reads the record before the task uses the link can get a certificate of that site for the run. Before #30, the inputs held whole startup kits, with private keys.

**Proposal.** A task may name secrets that the TES hands to executors, for example as files or variables, without storing their values in the task's record, and without returning them on `GET` of the task: the record shows only their names. Values come either with the request, and are dropped once handed over, or as references to a secret store that the TES trusts. A gateway passes them on in the same way, without logging them.

**What it changes here.** The one-time link, or any other credential of a run, leaves the task records. It doesn't solve how the WES authenticates to the TES of each site ([G5](gap-analysis.md#g5)), which is about the caller's credentials, not the task's.

### Pinning tasks by a property of a site

**Problem.** A task is pinned to a site by the URL of a TES: directly, or through proTES with the tag `gateway.backends` ([T4](../tests/t4-protes.md), [H11](../testbed/shortcuts.md#h11)). A run is tied to addresses, and nothing says which site holds which data. A federated job needs exactly one participant at each site that holds a share of the data, wherever that site's TES is.

**Proposal.** A task may state constraints on where it runs by properties of a site, or of the data it needs, rather than by an address: for example, the organization that runs a TES, as in the `organization` of its GA4GH service info, or a data identifier that only resolves at its site, as with DRS. A gateway routes the task to a TES that meets them, or refuses it when none does; a TES refuses a task whose constraints it doesn't meet. TES 1.1's `resources.zones` and `tags` don't carry this: zones are within a TES, and tags have no agreed meaning.

**What it changes here.** The WES's static map of sites becomes a lookup, in a registry such as the [Cloud Registry](https://github.com/elixir-cloud-aai/cloud-registry), and a site can move its TES without changing any sites file.

## ELIXIR On-Cloud

| Proposal | Gaps closed | Status |
|---|---|---|
| | | |

## NVFlare

| Proposal | Gaps closed | Status |
|---|---|---|
| | | |

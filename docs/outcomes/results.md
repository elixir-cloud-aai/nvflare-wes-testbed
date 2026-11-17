# Results

!!! note "Draft; real-site rows follow from [#10](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/10)"
    Section 5 holds draft outcomes and proposals, for further consideration, and only what test results support. So far, only two dress rehearsals are recorded, with the hub and both sites in one cluster on Rahti. Rows from partner nodes follow from the probes ([#3](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/3)) and the run with two or more sites. Whatever is added here stays a draft: it gets finalized elsewhere.

What each test showed on real sites, on which date. See "What to record" in each [test](../tests/index.md). For the local runs, see [Local runs](../tests/index.md#local-runs). What follows from these rows is in [Gap analysis](gap-analysis.md) and [Open questions](open-questions.md); a short text for the report is [below](#text-for-the-m45-report).

| Test | Node | Date | Expectation | Result |
|---|---|---|---|---|
| Node probe | The TESK of the T8 row below, in the hub's cluster on Rahti | 2026-11-12 | A task reaches the hub's FL port | `open`, at the hub's public address, from inside the same cluster (hairpin). From outside the cluster, the port answered too, to a plain connection. No task at another node has tried it yet |
| T8 | One TESK (chart 0.3.0, API 1.2.0), without authentication, in the hub's cluster on Rahti, as both sites | 2026-11-12 | The run ends `COMPLETE` | First run: `SYSTEM_ERROR` after the start timeout, as a probe listener left in the hub's pod held the FL port (runs now fail at once then, [#41](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/pull/41)). After a restart of the pod: `COMPLETE`, NVFlare job `FINISHED:COMPLETED`, both sites joined. Accuracies and task start times weren't recorded. No operator involved, as the node is ours |
| T8 | The same TESK, without authentication, in the hub's cluster on Rahti, as both sites | 2026-11-16 | The run ends `COMPLETE` | Run `6f2f6bd9`, after a fresh restart of the hub's pod: `COMPLETE`, NVFlare job `FINISHED:COMPLETED`. The FL port was closed before the run and open while it ran, so an idle hub couldn't be probed then (the hub answers probes between runs since [#47](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/pull/47), on Rahti since 2026-11-17). Accuracies and task start times weren't recorded. No operator involved, as the node is ours |

## Text for the M4.5 report

A short text for the report of milestone M4.5 of ECP work package 4, whose agreed result is a report based on the GA4GH Cloud AI/ML Working Group. It's a draft, like the rest of this page, from the local runs and from the two dress rehearsals above, and changes once partner nodes have taken part.

**Question.** Can a federated learning job with NVIDIA FLARE (NVFlare) run through the GA4GH Workflow Execution Service (WES), with its participants scheduled as tasks through the GA4GH Task Execution Service (TES) of each site, as the services of ELIXIR On-Cloud offer them? The testbed takes every shortcut it can, and [lists them](../testbed/shortcuts.md).

**What ran, on what.** A WES run, through a thin WES of the testbed, with the FL server beside the WES and one NVFlare client per site as a TES task ([option B1](../testbed/options.md#b1-server-beside-the-wes)):

- **Locally,** on laptops, 2026-11-04 and 2026-11-11: two Funnel instances as sites, directly and through the TES gateway proTES, with mutual TLS between participants. Clients only dial out, and no data of a site reaches the hub: only model updates do. With synthetic data, the federated model reached a holdout accuracy of 0.975, against 0.825 and 0.875 for the sites alone ([Local runs](../tests/index.md#local-runs)). Since then, sites make their own keys and send only signing requests, and the WES takes only callers with a token of a trusted OIDC issuer.
- **On Rahti,** the Kubernetes service of CSC, 2026-11-12 and 2026-11-16: the hub, deployed with its Helm chart, and both sites as tasks on one TESK without authentication, in the same cluster. Both runs ended `COMPLETE`, with the NVFlare job `FINISHED:COMPLETED` (rows above).

**What didn't run.** No partner node has taken part yet: the run with two or more nodes of other organizations is still to come ([#10](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/10)). No TES that checks tokens took part, nor proTES on a real node. The accuracies of the runs on Rahti weren't recorded. So far, this is a proof of concept on one cluster, and an analysis of what's missing, not a demonstration across organizations.

**What's missing.** TES has no service-like tasks (an address, a name and a port that others reach), no time limits, no way to hand a secret to a task outside its records, and no way to pin a task to a site by a property of the site rather than by an address. The FL server therefore runs outside TES, at a hub with a public port. See the [Gap analysis](gap-analysis.md), the [Open questions](open-questions.md), and the draft [Proposals](proposals.md) for TES.

**What this does not deliver.** ELIXIR Cloud is not "available" for federated learning in the sense of the milestone:

- **Authentication:** the WES trusts one issuer, every caller gets the same role in NVFlare, and the hub calls the TES of each site with a token of its own, not the researcher's. No TES that checks tokens has taken part.
- **Tenants:** one run at a time, kept in memory only, with no separation of users, studies or projects.
- **Sites' control:** sites run whatever job comes. There's no job approval, no site policy and no privacy filter of NVFlare; the data of the test set comes from public URLs that the WES chooses; and the hub, not the site, decides which sites take part.

Each of these is in [Shortcuts and hacks](../testbed/shortcuts.md), with the proper way.

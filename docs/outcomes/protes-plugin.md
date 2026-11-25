# A site plugin for proTES

!!! note "Draft"
    Section 5 holds draft outcomes and proposals, for further consideration, and only what test results support. This page comes from [T4](../tests/t4-protes.md), locally, and from the run through proTES at the FI and CZ Nodes ([Results](results.md), [#18](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/18)). Whatever is added here stays a draft: it gets finalized elsewhere.

What a plugin of [proTES](https://github.com/elixir-cloud-aai/proTES) would need so that a WES can send the tasks of a federated job to proTES and name sites rather than TES instances. It's a description, not a design: nothing here is built.

## What there is now

The hub pins each task to one TES with proTES's tag `gateway.backends` (`{"type": "allow", "backends": [...]}`), by the URL of the site's TES or by proTES's identifier of it (the site's `backend` in the sites file; [Through proTES](../setup/real-sites.md#through-protes)). proTES then uses that TES only, and refuses the task if it can't: no plugin is involved, and any routing plugin of proTES works with it. This is enough to run a federated job through proTES, but:

- **Sites are addresses.** The hub's sites file maps each site to a TES and to a share of the data ([H11](../testbed/shortcuts.md#h11), [G4](gap-analysis.md#g4)). Moving a site's TES changes every sites file that names it.
- **The pin is all the client can say.** proTES doesn't know that a task is one participant of a job, or which site it stands for: the tag `site` of the testbed's tasks means nothing to it.
- **One identity for all tasks.** proTES owns every task as the one user whose token the hub holds ([H25](../testbed/shortcuts.md#h25)), and a TES that takes proTES's own token sees proTES's client as the owner of all of them.

## What a site plugin would need

A routing plugin (a step of proTES's pipeline, among FOCA's plugins), selectable by clients, which picks exactly one TES instance for a task from a site it names:

| Need | Why | From |
|---|---|---|
| A site named by the task, not a TES: a tag such as `site`, or the data it needs (e.g., a DRS identifier whose server is the site's) | The WES knows sites and data, not where their TES is | T4; [Pinning tasks by a property of a site](proposals.md#pinning-tasks-by-a-property-of-a-site) |
| A map from sites to TES instances that proTES keeps, from its configuration or a registry ([Cloud Registry](https://github.com/elixir-cloud-aai/cloud-registry)), by properties such as the `organization` of a TES's service info | Sites move their TES without touching any WES | H11 |
| Strict: exactly one TES per site, never another, and a refusal (as for a pin: `503`, nothing kept) when the site is unknown or its TES refuses | A participant elsewhere doesn't find its data, and data must not move | proTES's pinning, [Through proTES](../setup/real-sites.md#through-protes) |
| The TES instance and the site in the stored task (as the tag `gateway.backend` is now) | The WES and its user see where each participant ran; owner-only TES show the task to proTES's client only | Results, run through proTES |
| A token for each site's TES, of that TES's audience, and later one exchanged from the caller's rather than proTES's own | Per site, per user; proTES gets one token per backend audience from 0.7.0 ([protes#488](https://github.com/elixir-cloud-aai/proTES/pull/488)), token exchange is [protes#501](https://github.com/elixir-cloud-aai/proTES/issues/501) | [H25](../testbed/shortcuts.md#h25), [G5](gap-analysis.md#g5) |
| What the plugin sends to whom (`data_transfers`) and keeps (`data_stored`), as proTES lists for its plugins: a registry lookup per task, a cache of the map | Operators and users see what leaves proTES | proTES's plugin listing |

## What a plugin can't do

- **All or nothing.** A federated job needs every participant at once; a routing plugin decides one task at a time. If one site refuses, the WES still has to cancel the others, as it does now ([T6](../tests/t6-site-loss.md)). That takes groups of tasks in proTES, or stays in the WES.
- **The server.** The FL server has no place in TES ([G1](gap-analysis.md#g1)), so it stays beside the WES, wherever tasks are routed.
- **Getting out.** Whether a site's tasks reach the FL server is the site's network ([G11](gap-analysis.md#g11)): a plugin could refuse sites that a [probe](../setup/real-sites.md#probing-a-node) found closed, but it can't open them.

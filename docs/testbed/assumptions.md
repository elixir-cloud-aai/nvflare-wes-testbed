# Assumptions and constraints

## Assumptions

| ID | Assumption | If it's wrong |
|---|---|---|
| A1 | A TES task at a node may open a connection to one address and port outside | B1 fails at that node. See [T8](../tests/t8-real-sites.md), [C4](options.md#c4-fedavg-as-a-plain-workflow) |
| A2 | TES nodes can pull a public image, and run it as a task for as long as a job lasts (minutes here) | That node can't take part |
| A3 | A task can write to `/tmp`, with or without root | Clients don't start. Checked locally only, with a read-only root and as non-root |
| A4 | TES nodes fetch inputs from `https` URLs without credentials | Kits can't get there |
| A5 | Nodes other than Funnel accept tasks with such inputs, called directly by the WES. For [stretch goal 2](index.md#goals), proTES forwards them as well, as it did for [T4](../tests/t4-protes.md) | That node can't take part. For proTES only: stretch goal 2 stays open, and the direct run isn't affected |
| A6 | There's a machine for the hub, with a public address and an open port, for the time of the event | No hub, no B1 |

## Constraints

| ID | Constraint | Consequence |
|---|---|---|
| C1 | TES has no ports, service names or lifetimes | Participants can't be servers, without hacks ([B2](options.md#b2-server-as-a-tes-task-too)) |
| C2 | TES has no secrets | Keys reach tasks through inputs ([H3](shortcuts.md#h3)) |
| C3 | NVFlare's clients must check the server's name against their kit | The server's name is fixed before the run |
| C4 | NVFlare needs the same version everywhere | One image for all participants, pinned to 2.9.0 |
| C5 | Conquest runs tasks in its own cluster, until [its open issue](https://github.com/elixir-cloud-aai/generic-issues/issues/28) is resolved | [Option A](options.md#a-nvflare-inside-conquest) can't show several sites yet |
| C6 | proTES picks among its configured TES instances; clients can only narrow that down | Sites that take part must be configured there |
| C7 | The test set is public or synthetic and tiny, and always will be | No claim about real training |

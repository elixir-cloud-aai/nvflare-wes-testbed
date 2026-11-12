# Results

!!! note "Draft, until after the event"
    Section 5 holds draft outcomes and proposals, for further consideration, and only what test results on real sites support. So far, only a dress rehearsal before the event is recorded. Whatever is added here stays a draft: it gets finalized elsewhere after the event.

What each test showed on real sites, on which date. See "What to record" in each [test](../tests/index.md). For the local runs, see [Local runs](../tests/index.md#local-runs).

| Test | Node | Date | Expectation | Result |
|---|---|---|---|---|
| Node probe | The TESK of the T8 row below, in the hub's cluster on Rahti | 2026-11-12 | A task reaches the hub's FL port | `open`, at the hub's public address, from inside the same cluster (hairpin) |
| T8 | One TESK (chart 0.3.0, API 1.2.0), without authentication, in the hub's cluster on Rahti, as both sites | 2026-11-12 | The run ends `COMPLETE` | First run: `SYSTEM_ERROR` after the start timeout, as a probe listener left in the hub's pod held the FL port (runs now fail at once then, [#41](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/pull/41)). After a restart of the pod: `COMPLETE`, NVFlare job `FINISHED:COMPLETED`, both sites joined. Accuracies and task start times weren't recorded. No operator involved, as the node is ours |

# Open questions

!!! note "Draft; real-site rows follow from [#10](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/10)"
    Section 5 holds draft outcomes and proposals, for further consideration, and only what test results support. The questions below come from the local runs and from the two dress rehearsals on Rahti, with the hub and both sites in one cluster. Answers from partner nodes follow from the probes ([#3](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/3)) and the run with two or more sites. Whatever is added here stays a draft: it gets finalized elsewhere.

Questions that the tests leave open, or raise. The questions for the tests themselves are in each [test](../tests/index.md).

| Question | Raised by | Answer |
|---|---|---|
| Does a TES task at a partner node get out to the hub's FL port, 30002 on Rahti, or to 443, and through what? | Node probe and [T8](../tests/t8-real-sites.md) on Rahti, 2026-11-12 and 2026-11-16, both in the hub's own cluster; [G11](gap-analysis.md#g11) | Open: the probes ([#3](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/3)), then [#10](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/10) |
| Does the probe's `open` on Rahti say anything about other nodes? | Node probe on Rahti, 2026-11-12 | No. The task reached the hub's public address from inside the same cluster: its traffic went out and back in (hairpin). The port also answered a plain connection from outside the cluster. Whether a task at another node gets there is untested, as no partner node has taken part: that's the first question above |
| Does the federated model reach the holdout accuracies of [T1](../tests/t1-simulator.md) on real sites? | T8 on Rahti, 2026-11-12 and 2026-11-16: both runs ended with the NVFlare job `FINISHED:COMPLETED`, without the accuracies recorded | Open: the run with two or more sites checks them ([#10](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/10)) |
| How long does a task take to start at a node, and do the job's timeouts allow for it? | T8 on Rahti, 2026-11-12 and 2026-11-16: start times weren't recorded | Open: [#10](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/10) |
| Can the hub get tokens for the TES of a partner node from a real identity provider, and renew them during a run? | `tests/tokens_test.py`, with a mock provider only ([G5](gap-analysis.md#g5)) | Open: no TES that checks tokens has taken part yet |
| Has any real node a way to give a task an address, a name and a port that others reach? | [T5](../tests/t5-server-task.md), local, 2026-11-04 and 2026-11-11 ([G1](gap-analysis.md#g1)) | Open: to ask node operators along with the probe, without planning on it |
| Does the direct run also work through proTES and a TES that checks proTES' tokens? | [T4](../tests/t4-protes.md), local only | Open: the [stretch goal](../testbed/index.md#goals) ([#18](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/18)) |
| Is the hub's 2 GiB memory limit on Rahti enough for more than the test set's job? | T8 on Rahti, 2026-11-12: it ran within the limit ([What differed on Rahti](../setup/real-sites.md#what-differed-on-rahti)) | Open for bigger jobs and more sites; models and performance are out of [scope](../testbed/index.md#scope) |

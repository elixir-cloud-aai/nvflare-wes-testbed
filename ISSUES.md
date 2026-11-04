# Issues

**History: these are [on GitHub](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues) now, which is where they're kept up to date. Decisions since then aren't reflected here, such as direct calls first, instead of through proTES.**

To be created on GitHub once the repository exists, in this order. Labels are from the organization's set. "Blocked by" refers to the numbers here. Every issue is one pull request, or a task with no pull request where it says so.

The event is the BioHackathon. Everything up to and including #9 should be done before it. No people named here on purpose: assign them when creating the issues.

---

## 1. Publish the testbed's images to a registry

**Labels:** `type: ci / cd`, `priority: high`, `workload: hours`

**Body:** Nodes can't build images, and Funnel here finds them locally. Add a workflow that builds and pushes the participant image on pushes to `dev` (`release.yml` or a job in `ci.yml`, after checking which fits), under the organization's registry account. Make `FL_IMAGE` the pushed image. Stays a sandbox image: no signing needed. Check that `.dockerignore` keeps out everything but what's listed.

**Blockers:** none. Needs the organization's Docker Hub secrets: the maintainer.

## 2. Make a probe task for TES nodes

**Labels:** `type: testing`, `priority: critical`, `workload: hours`

**Body:** A small TES task that tells us what a node allows, before anyone relies on it. Runs the image; reports through its log whether it can reach `<hub>:8002` and `<hub>:443`, whether an `https` input arrives, whether `env` is passed, who it runs as, and whether `/tmp` is writable. A script that submits it to a TES URL or through proTES, and prints the outcome. Extend `tests/probe.py`, and document it in `docs/setup/real-sites.md`. This decides whether option B1 works at a node at all, and it's the first thing to run: **the biggest risk of the plan is here.**

**Blockers:** #1

## 3. Ask node operators to run the probe

**Labels:** `type: question`, `priority: critical`, `workload: hours`

**Body:** No pull request. Who's needed: **one operator per TES node that might take part; at least two nodes**, of those that are already in the Cloud Registry. Ask the questions in `docs/setup/real-sites.md`, and whether they'll have a person at or near the event. Needs node access for whoever runs the tests, which means credentials for the TES or proTES in use, through the channels the nodes use. Credentials never go into this repository. Record per node, without hostnames: which ports got out, and what's in the way.

**Blockers:** #2

## 4. Deploy the hub on a reachable machine

**Labels:** `type: delivery`, `priority: critical`, `workload: hours`

**Body:** A machine with a public address, the FL port open, and HTTPS for the WES. Add a Compose file for it: hub only, `FL_SERVER_NAME` and `WES_INTERNAL_URL` from the environment, `WES_SITES` from a file that isn't committed, with no Funnel or Docker socket. HTTPS through a reverse proxy, with the FL port passed straight through, as its TLS is mutual. Update `docs/setup/real-sites.md`. Who's needed: someone who can provide the machine and a name for it, the maintainer or an operator.

**Blockers:** #1

## 5. Restrict the WES on the public hub

**Labels:** `type: security`, `priority: high`, `workload: hours`

**Body:** There's no authentication ([H5](docs/testbed/shortcuts.md#h5)), and on a public machine anyone could start runs. Cheapest fix that's good enough for an event: at the reverse proxy, restrict `/ga4gh/wes/v1` by address or with a shared secret. `/kits` stays reachable from nodes, as does the FL port. The secret stays out of the repository. Say plainly that it's not LS Login.

**Blockers:** #4

## 6. Host the test set for real sites

**Labels:** `type: feature`, `priority: high`, `workload: minutes`

**Body:** Nodes need a URL for their site's share. For the event it can be public, as it's synthetic: raw files of this repository, at a fixed commit, are enough. Document which site gets which, and that this is [H13](docs/testbed/shortcuts.md#h13). **Public or synthetic data only: no clinical data and no data from Trusted Research Environments, ever.**

**Blockers:** none

## 7. Run a real-site job with one site

**Labels:** `type: testing`, `priority: high`, `workload: hours`

**Body:** No pull request other than recording results. [T8](docs/tests/t8-real-sites.md) with one node, before the event if possible, as a dress rehearsal. A job with `min_clients` of 1 needs exporting (small change to `testset/job_src/job.py`). Results go to `docs/outcomes/results.md`, without hostnames.

**Blockers:** #3, #4, #5, #6

## 8. Plan the session at the event

**Labels:** `type: delivery`, `priority: high`, `workload: hours`

**Body:** No code. A session plan in `docs/tests/index.md`, or a page next to it: goal, order of tests, what counts as success, and who does what. **Roles needed:** one person for the hub, one operator per node, one person submitting runs, one taking notes for the report. Have a fallback, in order: two real nodes, one real node plus one local, a local run on the projector and the analysis.

**Blockers:** #3

## 9. Decide on going through proTES at the event

**Labels:** `type: question`, `priority: medium`, `workload: minutes`

**Body:** No pull request. Either a test deployment of proTES with the nodes configured, and `gateway.backends` allowed, or direct calls to each TES from the WES. The latter means fewer things that can go wrong; the former shows the architecture. Depends on who can configure the deployment, and on its authentication: the WES needs a token for it. Recommended: direct at first, proTES once one site works.

**Blockers:** #3

## 10. Run the federated job at the event

**Labels:** `type: testing`, `priority: critical`, `workload: days`

**Body:** [T8](docs/tests/t8-real-sites.md) with two or more nodes, following the plan of #8. Record results in `docs/outcomes/results.md`. Try port 443 ([T7](docs/tests/t7-port-443.md)) where 8002 doesn't get out.

**Blockers:** #7, #8, #9

## 11. Write up outcomes for the M4.5 report

**Labels:** `type: docs`, `priority: high`, `workload: hours`

**Body:** Fill in `docs/outcomes/` from results, as drafts: open questions, gap analysis, proposals. Add a short text for the report based on the GA4GH Cloud AI/ML Working Group, saying what ran, on what, and what didn't. Say plainly what this doesn't deliver: ELIXIR Cloud isn't "available" for this yet, in the sense of authentication, tenants or sites' control.

**Blockers:** #10

## 12. Talk to the owner of Conquest about NVFlare

**Labels:** `type: question`, `priority: medium`, `workload: minutes`

**Body:** No pull request. For the maintainer. Show [options A1 and A2](docs/testbed/options.md#a-nvflare-inside-conquest), and what ran. Questions: would a workflow type be welcome, or rather not in Conquest at all? What's the state of the external TES ([generic-issues#28](https://github.com/elixir-cloud-aai/generic-issues/issues/28))? Should anyone try a dirty branch?

**Blockers:** none

## 13. Try NVFlare on Conquest, on a local branch

**Labels:** `type: feature`, `priority: low`, `workload: hours`

**Body:** Only if #12 says so. Option A1 on a local dirty branch, with a local cluster: a `RunAdapter` for `NVFLARE`, with the runner carrying the logic of `wes/app.py`. No push to its upstream. Describe the branch in this repository's docs. It shows something real across sites only after the external TES.

**Blockers:** #12

## 14. Fallback: FedAvg as a plain workflow

**Labels:** `type: feature`, `priority: medium`, `workload: hours`

**Body:** Only if #3 shows that nodes don't let tasks out. Option [C4](docs/testbed/options.md#c4-fedavg-as-a-plain-workflow): rounds of tasks with the same test set, with a Nextflow or Snakemake workflow, or at first a plain script calling TES, with models through object storage. Find out how to pin tasks to sites from the engine, or use the script.

**Blockers:** #3

## 15. Keep site keys at the sites

**Labels:** `type: security`, `priority: medium`, `workload: hours`

**Body:** [H3](docs/testbed/shortcuts.md#h3) and [H4](docs/testbed/shortcuts.md#h4) are the worst of the hacks. Try `nvflare cert` and `nvflare package`: a site's key is made in the task or kept at the site, and only a signing request and certificate travel. Find out how far that gets without any secrets in task records, and what TES would have to offer otherwise. Only after the event, and if there's a reason to go on.

**Blockers:** #10

## 16. Propose what TES lacks

**Labels:** `type: docs`, `priority: low`, `workload: hours`

**Body:** A draft for the GA4GH Federated Analysis Work Stream and the Cloud AI/ML Working Group: service-like tasks (address, name, port, time limit), secrets for tasks, pinning by a property of a site. Based on [T5](docs/tests/t5-server-task.md) and on results of the event, in `docs/outcomes/proposals.md`. Nothing is posted anywhere without the maintainer's OK.

**Blockers:** #10

## 17. Add linters to CI

**Labels:** `type: maintenance`, `priority: low`, `workload: minutes`

**Body:** ruff, gitleaks and actionlint through pre-commit, as in the organization's other repositories. Add the job to the `needs` of the gate. Only if the repository lives past the event.

**Blockers:** none

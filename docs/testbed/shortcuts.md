# Shortcuts and hacks

All of them, in one place, each with the proper way. Their numbers are referred to from the code. Any of these is a reason not to run this with anything real.

## Credentials and security

### H3

**Startup kits, with private keys, are inputs of TES tasks.** They come from an unguessable link at the WES, over plain HTTP here. That link is in the task records of TES and proTES, and in Funnel's logs: anyone who can read those can get a site's key while the run lasts. The WES kills the link when the run ends; each run has a CA of its own, valid for 2 days, so a leaked key is useless soon after. **Proper way:** a way of handing secrets to tasks that keeps them out of records. That's missing from TES: site-held keys ([H4](#h4)) avoid the need.

**Update:** a site's task now carries an unguessable link to sign its own certificate signing request (`/sites/{token}/csr`) instead of to download a kit. It's still in the same task records and logs, but what it grants is now one certificate over a key the site already made itself, not the key, and the WES deletes the slot the moment it's used, not only at the run's end. The rest holds: a way of handing even this out of task records would still be better, though there's no longer a private key, or a reusable slot, behind it to leak.

### H4

**The WES makes all private keys, including the sites'.** It's central provisioning with `nvflare provision`, so the WES can impersonate anyone. **Proper way:** sites generate their keys and send signing requests, for which NVFlare has [`nvflare cert` and `nvflare package`](../about/references.md#nvflare), or per-job certificates.

**Update:** resolved for sites. Each run's FL server and admin are still provisioned centrally, by the WES itself, through `nvflare cert request`, `approve` and `package` run locally one after another: there's no reason not to for these two, and it's the only way to share one CA with the sites, as there's no documented way to import an existing CA into `nvflare cert init`. A site, though, now makes its own key inside its TES task, and sends this service only a signing request over H3's one-time link; the signed certificate it gets back is the only thing that travels. Certificates stay short-lived (`--valid-days 2` on the run's CA), as in the original design.

### H5

**The thin WES has no authentication, and one admin identity for all users.** Anyone who reaches it can start runs and download models. **Proper way:** LS Login and a real service framework (see [FOCA](https://github.com/elixir-cloud-aai/foca)), or Conquest with its planned access control, with the user's identity passed to NVFlare.

**Update:** `/runs*` and `/outputs` now check a caller's bearer token against one trusted OIDC issuer (`WES_OIDC_ISSUER`), FOCA's own auth model (a trusted-issuer list, JWKS from the issuer's discovery document) borrowed without the rest of FOCA, which is Connexion on Flask and would mean leaving FastAPI. LS Login is the intended issuer for a real deployment; nothing here is specific to it. It's off unless configured, so the local sandbox stays as it was: a deliberate, named gap, not a silent one. `/service-info` stays open regardless, as a client has to discover how to authenticate before it has a token. `/kits` and `/sites/*/csr` are untouched: a different actor (a site or a task holding a one-time link, [H3](#h3)/[H4](#h4)), not a researcher with an identity. Still one admin identity for every caller: the validated identity isn't yet passed to NVFlare, so this closes "anyone can reach it," not "one identity for all users" — that part is a follow-up.

### H7

**Plain HTTP between the WES, proTES and TES, in the local testbed.** Only FLARE's own connections use TLS, there. On [real sites](../setup/real-sites.md#deploying-the-hub), links to kits go over HTTPS, through a reverse proxy. **Proper way:** HTTPS everywhere, which real nodes have anyway.

### H9

**Funnel runs as root with the Docker socket,** to run executors as sibling containers, which amounts to root on the host. The network of a site is hard-coded in its run template, and "pull" is replaced by a check for the local image. **Proper way:** a real node.

### H10

**A fake identity provider for proTES hands out tokens to anyone.** **Proper way:** LS Login, as in the [token exchange testbed](https://github.com/elixir-cloud-aai/token-exchange-flow-testbed).

## Scheduling

### H1

**The FL server isn't scheduled through TES.** It's a child process of the WES, with a fixed port and name. **Proper way:** a reachable long-running service at a known address, deployed and monitored as such, with [studies](../about/references.md#nvflare) to separate users, or TES with [service tasks](../background/design.md#scheduling-participants).

### H2

**One run at a time, all state in memory, no restart.** Ports are fixed, so a second server wouldn't fit, and a restart forgets runs. **Proper way:** a database and a queue, as in any real WES, and a port per run or one long-running server.

### H6

**Server as a TES task (T5 only):** that TES is configured to give each of its executors a fixed name on the networks of all sites. There's no such thing in TES, and it only works because everything is on one Docker host. **Proper way:** B1's hub, or TES with service tasks.

### H11

**Sites are a static map in the WES's environment, and tasks are pinned by a TES's URL.** The tag `gateway.backends` does what's needed, but ties a client to an address. **Proper way:** [Cloud Registry](https://github.com/elixir-cloud-aai/cloud-registry) for what exists, and a routing plugin of proTES by site or by where the data is.

### H14

**Time limits are a `timeout` around the client (30 minutes) and constants in the WES.** Clients retry forever otherwise. **Proper way:** a limit on the task that its backend enforces, which isn't in TES.

### H15

**Tasks end because the admin API shuts the federation down.** A client's exit code says nothing about the job: only the WES knows that. **Proper way:** participants tied to a job, as NVFlare's job launchers do.

### H18

**Any site lost means a failed run** ([T6](../tests/t6-site-loss.md)), and sites never rejoin. `min_clients` is the number of sites, and tasks aren't retried. **Proper way:** let the job tolerate a lost site, by setting `min_clients` and timeouts of the workflow according to what the study needs, and restart a lost client.

## WES

### H8

**`NVFLARE` is an invented workflow type, and `workflow_url` is the name of a job in the image.** No uploads, so users can't bring code. **Proper way:** a registered type, jobs from TRS, signed and versioned, which sites can review.

### H17

**Task states are in `system_logs` of `task_logs`,** and `outputs` holds relative URLs and the job's status. **Proper way:** full TES records in the fields of the WES specification, and a real outputs location.

## Data and privacy

### H12

**The test's user compares models using the data of all sites** (`tests/e2e.py` reads the test set directly). Fine for synthetic data, and against the whole idea otherwise. **Proper way:** evaluate at each site, or on a separate public set.

### H13

**A site's data is a `file://` URL into Funnel's container, or a [public URL](../setup/real-sites.md#the-test-set) at the event, and the WES chooses it.** **Proper way:** an identifier that only resolves at the site, as with DRS, and access decided by the site.

### H16

**No privacy filters, no job approval.** Model weights go to the server unprotected, apart from TLS, and sites run whatever job comes. **Proper way:** NVFlare's filters, such as differential privacy or homomorphic encryption, and its [site policies](../about/references.md#nvflare) for approving jobs.

## The testbed itself

### H19

**Two "sites" on one laptop.** They share a kernel, a Docker daemon and an image store. Docker networks without a route stand in for firewalls. **Proper way:** [real sites](../setup/real-sites.md).

### H20

**A loose image.** One image holds all participants, the WES and the tests, on Python 3.12, with version ranges for most packages. Pushed to Docker Hub without scans or signatures, with only the default build provenance. **Proper way:** separate images, locked dependencies, and signing, as in the other repositories of the organization.

### H21

**Light process.** A quick proof of concept, by decision: no reviews by other tools and no coverage target. Conventions of the organization apply only to CI and commits.

# Real sites

!!! warning "Untested"
    None of this has run. It's what we expect it to take: see [T8](../tests/t8-real-sites.md) and [ISSUES.md](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/blob/dev/ISSUES.md).

## What the hub needs

A machine with a public address, Docker, and these open: the FL port (8002, or 443 with [T7](../tests/t7-port-443.md)), and HTTPS for the WES, as tasks fetch their kits from it. It needs a stable name, set in `FL_SERVER_NAME` and `WES_INTERNAL_URL`: the kits contain it. The WES has no authentication ([H5](../testbed/shortcuts.md#h5)), so restrict who can reach `/ga4gh/wes/v1`, for example to the addresses of the people at the event, or tunnel to it, and keep the `/kits` path open for nodes.

## What each site needs

- A TES, known to the proTES in use, or reached directly.
- A task may open connections to the hub's FL port and HTTPS, may pull the public image, and may write to `/tmp`.
- A URL for its share of the test set, which here may simply be public. **Public or synthetic data only: no clinical data and no data from Trusted Research Environments, ever.**

## What to ask node operators

1. May a TES task connect out to `<hub>:8002`, or `<hub>:443`? Through a proxy?
2. Are there limits on the run time of tasks? A run of the test set takes under a minute.
3. Which TES version and backend is it? Does it take `http(s)` inputs, and does it have a size limit for them? Does it pass `env` to executors?
4. Can it pull images from Docker Hub, and does it enforce non-root or read-only containers? (Either's fine.)
5. Who has access to task records and logs? They'd see the kit links ([H3](../testbed/shortcuts.md#h3)), for test federations only, which end with the run.

## What changes in the setup

- `WES_SITES` holds the real TES URLs and data URLs.
- `FL_IMAGE` names the image in a registry.
- `compose/protes.yaml` lists the real TES instances, with their `auth`.

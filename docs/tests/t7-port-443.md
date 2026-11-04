# T7 Only port 443

## Description

Real nodes may only let tasks out on port 443. NVFlare's `http` scheme (WebSocket) with `fed_learn_port: 443` covers that, and needs the FL port to be free on the hub. Whether a proxy or ingress in between would pass it wasn't tried: here, it's a direct connection, and TLS is mutual, so a terminating proxy wouldn't work.

## Expectations

1. As in T2.
2. Clients connect to `http://fl-hub:443`.

## Steps

```sh
FL_SCHEME=http FL_PORT=443 docker compose --profile test run --rm e2e
docker compose logs funnel-site-1 | grep -o 'ACTIVE [a-z]*://fl-hub:[0-9]*' | sort -u
docker compose --profile test down -v
```

(In Fish: `env FL_SCHEME=http FL_PORT=443 docker compose ...`.)

## Questions it answers

If a node lets out only 443, is that enough?

## What to record

On a real node: whether this worked where 8002 didn't, and what's in between.

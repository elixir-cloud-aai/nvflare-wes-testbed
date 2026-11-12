# T9 The WES's OIDC gate

## Description

As [T2](t2-wes-to-tes.md), with the WES checking every caller's bearer token against a trusted issuer ([H5](../testbed/shortcuts.md#h5)): mandatory, with no local-only bypass. `compose.yaml` always includes a fake identity provider (the same one [H10](../testbed/shortcuts.md#h10) uses for proTES), so this runs with no extra setup, unlike [T4](t4-protes.md).

## Expectations

1. `GET /ga4gh/wes/v1/runs` without a token: `401`.
2. The same, with a token the fake identity provider issued: `200`.
3. `GET /ga4gh/wes/v1/service-info` without a token: `200` (a client has to be able to discover how to authenticate before it has a token).

Claim mismatches (wrong audience, issuer, signature, an expired token) are checked separately, against a fake key with no network at all, by `tests/auth_check.py` (run through `tests/hub.sh`, and in CI). T2 itself also checks that a completed run's log names its submitter.

## Steps

```sh
docker compose --profile test build
docker compose --profile test run --rm auth-e2e-check
docker compose --profile test down -v
```

## Questions it answers

- Does a request with no `Authorization` header get refused once an issuer is configured? It does, with `401`.
- Does `/service-info` stay reachable regardless, so a client can find out how to authenticate? It does.

## What to record

Whether the fake identity provider's token was accepted on the first try; any difference from T4's own use of the same fake provider.

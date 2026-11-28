# T9 The WES's OIDC gate

## Description

As [T2](t2-wes-to-tes.md), with the WES checking every caller's bearer token against a trusted issuer ([H5](../testbed/shortcuts.md#h5)): mandatory, with no local-only bypass. `compose.yaml` always includes a fake identity provider (the same one [H10](../testbed/shortcuts.md#h10) uses for proTES), so this runs with no extra setup, unlike [T4](t4-protes.md).

## Expectations

1. `GET /ga4gh/wes/v1/runs` without a token: `401`.
2. The same, with a token the fake identity provider issued: `200`.
3. `GET /ga4gh/wes/v1/service-info` without a token: `200` (a client has to be able to discover how to authenticate before it has a token).
4. `POST /ga4gh/wes/v1/runs`, which needs the entitlement that `compose.yaml` requires (`WES_OIDC_REQUIRED_ENTITLEMENTS`, [#70](https://github.com/elixir-cloud-aai/nvflare-wes-testbed/issues/70)), which the fake identity provider releases at userinfo only, as LS Login does: a member gets as far as the request (`400` for a workflow the WES doesn't have); a subject in another group only (`outsider-1`) gets `403`, and still lists runs, none of them others'.
5. CORS, for the origin `compose.yaml` allows the WES (`WES_CORS_ALLOWED_ORIGINS`): a browser's preflight for `POST /ga4gh/wes/v1/runs` with `Authorization` gets `200` and that origin, and the `401` of step 1 carries it too, so a page can read it.

The rest of CORS (other origins, other methods and headers, no CORS for `/kits`, `/sites` and `/outputs`, none without the setting, and what the setting takes) is checked in process, with no network, by `tests/cors_check.py` (`cors-check`, run through `tests/hub.sh`, and in CI). The entitlement in detail (from the token or from userinfo; the parent group, a sibling or a subgroup alone get `403`; userinfo that fails, refuses the token or answers about another subject gets `401` and isn't kept; the cache per token and its bounds; the allow-list on top; what the settings take; nothing of tokens or entitlements in the logs) is checked in process, with no network, by `tests/entitlement_check.py` (`entitlement-check`, run through `tests/hub.sh`, and in CI). Claim mismatches (wrong audience, issuer, signature, an expired token), and how the FLARE admin is named with and without an `email` claim, are checked separately, against a fake key with no network at all, by `tests/auth_check.py` (run through `tests/hub.sh`, and in CI). T2 itself also checks that a completed run's log names its submitter.

## Steps

```sh
docker compose --profile test build
docker compose --profile test run --rm auth-e2e-check
docker compose --profile test down -v
```

## Questions it answers

- Does a request with no `Authorization` header get refused once an issuer is configured? It does, with `401`.
- Does `/service-info` stay reachable regardless, so a client can find out how to authenticate? It does.
- Does starting a run need the required entitlement, also when only userinfo has it? It does: `403` without it.

## What to record

Whether the fake identity provider's token was accepted on the first try; any difference from T4's own use of the same fake provider.

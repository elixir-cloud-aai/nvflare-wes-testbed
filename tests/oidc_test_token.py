"""Get a token from the fake identity provider, for tests that call the WES itself.

Separate from `TES_GATEWAY_TOKEN_URL`: that one is the WES authenticating itself
to proTES (H10); `WES_OIDC_TOKEN_URL` is a caller authenticating to the WES (H5).
"""

import os

import requests


def fetch(sub: str = "researcher-1") -> str:
    """Get an access token for a subject, from `WES_OIDC_TOKEN_URL`.

    Args:
        sub: Subject to ask a token for.

    Returns:
        The token.
    """
    reply = requests.get(os.environ["WES_OIDC_TOKEN_URL"], params={"sub": sub}, timeout=30)
    return reply.json()["access_token"]


def header(sub: str = "researcher-1") -> dict[str, str]:
    """Build the `Authorization` header a WES call needs.

    Args:
        sub: Subject to ask a token for.

    Returns:
        The header.
    """
    return {"Authorization": f"Bearer {fetch(sub)}"}

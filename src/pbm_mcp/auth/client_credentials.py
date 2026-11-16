"""Config slot for OAuth2 client credentials.

The token endpoint, client id, and client secret can be set in the environment.
The token request itself is not implemented until that URL is known and reviewed.
"""

from __future__ import annotations

import httpx2


class ClientCredentialsAuth(httpx2.Auth):
    """Holds the client-credentials settings. Requests fail closed."""

    def __init__(self, token_url: str, client_id: str, client_secret: str) -> None:
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret

    def auth_flow(self, request: httpx2.Request):
        raise NotImplementedError(
            "client-credentials auth is not implemented until a token URL is configured"
        )
        yield request

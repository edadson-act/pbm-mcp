"""Bearer token taken from the environment, shared by every request."""

from __future__ import annotations

import httpx2

from pbm_mcp.config import ConfigError


class BearerEnvAuth(httpx2.Auth):
    def __init__(self, token: str) -> None:
        if not token:
            raise ConfigError(
                "bearer-env auth requires PBM_BEARER_TOKEN or a per-API BEARER_TOKEN."
            )
        self._token = token

    def auth_flow(self, request: httpx2.Request):
        request.headers["Authorization"] = f"Bearer {self._token}"
        yield request

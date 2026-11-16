"""Static API key or subscription key header."""

from __future__ import annotations

import httpx2

from pbm_mcp.config import ConfigError


class ApiKeyAuth(httpx2.Auth):
    def __init__(self, header_name: str, api_key: str) -> None:
        if not header_name.strip():
            raise ConfigError("API key header name is empty.")
        if not api_key:
            raise ConfigError("API key auth requires PBM_API_KEY or a per-API API_KEY.")
        self._header_name = header_name
        self._api_key = api_key

    def auth_flow(self, request: httpx2.Request):
        request.headers[self._header_name] = self._api_key
        yield request

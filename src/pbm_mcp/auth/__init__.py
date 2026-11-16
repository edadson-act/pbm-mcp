"""Select the upstream credential strategy for one PBM API."""

from __future__ import annotations

import httpx2

from pbm_mcp.auth.api_key import ApiKeyAuth
from pbm_mcp.auth.bearer_env import BearerEnvAuth
from pbm_mcp.auth.client_credentials import ClientCredentialsAuth
from pbm_mcp.auth.forward import ForwardAuth
from pbm_mcp.auth.none import no_auth
from pbm_mcp.config import ConfigError, Settings

UpstreamAuth = httpx2.Auth | None


def build_auth(settings: Settings, domain_id: str) -> UpstreamAuth:
    """Build the httpx auth for ``domain_id``.

    ``client-credentials`` raises ``NotImplementedError``. The settings fields
    for that mode exist, and the server skips a domain that selects it.
    """
    mode = settings.auth_mode_for(domain_id)
    if mode == "none":
        return no_auth()
    if mode == "api-key":
        return ApiKeyAuth(
            header_name=settings.api_key_header_for(domain_id),
            api_key=settings.api_key_for(domain_id),
        )
    if mode == "bearer-env":
        return BearerEnvAuth(settings.bearer_token_for(domain_id))
    if mode == "forward":
        return ForwardAuth()
    if mode == "client-credentials":
        raise NotImplementedError(
            "client-credentials auth is not implemented until a token URL is configured"
        )
    raise ConfigError(f"Unknown auth mode {mode!r}.")


__all__ = ["ClientCredentialsAuth", "UpstreamAuth", "build_auth"]

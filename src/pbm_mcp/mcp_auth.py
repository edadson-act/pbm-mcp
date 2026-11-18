"""Bearer token required of callers of the MCP HTTP endpoint.

This is separate from upstream PBM credentials. Tailscale Funnel publishes the
local port on the public internet, so the token is what keeps ``/mcp`` closed.
"""

from __future__ import annotations

import hashlib
import hmac

from fastmcp.server.auth import AccessToken, AuthProvider, TokenVerifier

from pbm_mcp.catalog import CATALOG
from pbm_mcp.config import ConfigError, Settings

MIN_TOKEN_LENGTH = 16
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class McpBearerAuth(TokenVerifier):
    """Accept one shared secret presented as ``Authorization: Bearer``."""

    def __init__(self, token: str) -> None:
        if token.lower().startswith("bearer "):
            raise ConfigError(
                "PBM_MCP_BEARER_TOKEN must be the secret only. "
                "Callers send it as Authorization: Bearer <secret>."
            )
        if len(token) < MIN_TOKEN_LENGTH:
            raise ConfigError(
                "PBM_MCP_BEARER_TOKEN must be at least "
                f"{MIN_TOKEN_LENGTH} characters. "
                "Generate one with `openssl rand -hex 32`."
            )
        super().__init__()
        self._digest = hashlib.sha256(token.encode()).digest()

    async def verify_token(self, token: str) -> AccessToken | None:
        digest = hashlib.sha256(token.encode()).digest()
        if not hmac.compare_digest(digest, self._digest):
            return None
        return AccessToken(
            token=token,
            client_id="pbm-mcp",
            scopes=[],
            claims={},
        )


def build_mcp_auth(settings: Settings) -> McpBearerAuth | None:
    """Return endpoint auth when ``PBM_MCP_BEARER_TOKEN`` is set."""
    token = settings.mcp_bearer_token.strip()
    if not token:
        return None
    return McpBearerAuth(token)


def ensure_reachable_bind(settings: Settings, auth: AuthProvider | None) -> None:
    """Refuse a non-loopback bind while the MCP endpoint is unauthenticated."""
    if auth is not None:
        return
    host = settings.host.strip().lower().strip("[]")
    if host in LOOPBACK_HOSTS:
        return
    raise ConfigError(
        f"PBM_HOST={settings.host!r} accepts connections from other machines. "
        "Set PBM_MCP_BEARER_TOKEN before starting."
    )


def inbound_authorization_is_forwarded(settings: Settings) -> bool:
    """True when any API would copy the caller's Authorization header upstream."""
    for domain in CATALOG:
        try:
            mode = settings.auth_mode_for(domain.id)
        except ConfigError:
            continue
        if mode == "forward":
            return True
    return False

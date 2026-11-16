"""Copy the inbound MCP Authorization header onto the upstream call.

FastMCP strips ``Authorization`` when it forwards headers, so a member token
stays request-scoped only if this auth flow puts it back.
"""

from __future__ import annotations

import httpx2
from fastmcp.server.dependencies import get_http_request


class ForwardAuth(httpx2.Auth):
    def auth_flow(self, request: httpx2.Request):
        header = _inbound_authorization()
        if header:
            request.headers["Authorization"] = header
        yield request


def _inbound_authorization() -> str | None:
    try:
        incoming = get_http_request()
    except RuntimeError:
        return None
    value = incoming.headers.get("authorization")
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None

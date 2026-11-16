import logging

import httpx2
import pytest
from fastmcp import Client

from pbm_mcp.auth import build_auth
from pbm_mcp.auth.forward import ForwardAuth
from pbm_mcp.server import build_server
from tests.helpers import (
    capture_transport,
    make_settings,
    tool_names,
    write_allowlist,
    write_openapi,
)


class _Headers:
    def __init__(self, authorization: str | None) -> None:
        self._authorization = authorization

    def get(self, key: str, default: str | None = None) -> str | None:
        if key.lower() == "authorization":
            return self._authorization
        return default


class _Request:
    def __init__(self, authorization: str | None) -> None:
        self.headers = _Headers(authorization)


def _claim_server(tmp_path, monkeypatch, **settings_kwargs):
    monkeypatch.setenv("PBM_CLAIM_HISTORY_BASE_URL", "https://claims.test")
    settings = make_settings(tmp_path, **settings_kwargs)
    write_openapi(settings, "claim-history")
    write_allowlist(settings, "claim-history", [{"id": "listClaims"}])
    return settings


async def test_api_key_header_is_sent(tmp_path, monkeypatch):
    settings = _claim_server(tmp_path, monkeypatch, auth_mode="api-key", api_key="secret-key")
    seen: dict = {}
    server = build_server(settings, transport=capture_transport(seen))
    async with Client(server) as client:
        result = await client.call_tool("claim_history_listClaims", {"memberId": "m-1"})
    assert result.data == {"ok": True}
    assert seen["headers"]["x-api-key"] == "secret-key"
    assert "authorization" not in seen["headers"]
    assert seen["url"] == "https://claims.test/claims?memberId=m-1"


async def test_bearer_env_header_is_sent(tmp_path, monkeypatch):
    settings = _claim_server(
        tmp_path,
        monkeypatch,
        auth_mode="bearer-env",
        bearer_token="env-token",
    )
    seen: dict = {}
    server = build_server(settings, transport=capture_transport(seen))
    async with Client(server) as client:
        await client.call_tool("claim_history_listClaims", {"memberId": "m-1"})
    assert seen["headers"]["authorization"] == "Bearer env-token"


async def test_forward_copies_inbound_authorization(tmp_path, monkeypatch):
    settings = _claim_server(tmp_path, monkeypatch, auth_mode="forward")
    monkeypatch.setattr(
        "pbm_mcp.auth.forward.get_http_request",
        lambda: _Request("Bearer member-token"),
    )
    seen: dict = {}
    server = build_server(settings, transport=capture_transport(seen))
    async with Client(server) as client:
        await client.call_tool("claim_history_listClaims", {"memberId": "m-1"})
    assert seen["headers"]["authorization"] == "Bearer member-token"


async def test_forward_without_request_sends_no_authorization(tmp_path, monkeypatch):
    settings = _claim_server(tmp_path, monkeypatch, auth_mode="forward")

    def missing_request():
        raise RuntimeError("No active HTTP request found.")

    monkeypatch.setattr("pbm_mcp.auth.forward.get_http_request", missing_request)
    seen: dict = {}
    server = build_server(settings, transport=capture_transport(seen))
    async with Client(server) as client:
        await client.call_tool("claim_history_listClaims", {"memberId": "m-1"})
    assert "authorization" not in seen["headers"]


async def test_per_domain_auth_mode_override(tmp_path, monkeypatch):
    settings = _claim_server(tmp_path, monkeypatch, auth_mode="none")
    monkeypatch.setenv("PBM_CLAIM_HISTORY_AUTH_MODE", "api-key")
    monkeypatch.setenv("PBM_CLAIM_HISTORY_API_KEY", "domain-key")
    monkeypatch.setenv("PBM_CLAIM_HISTORY_API_KEY_HEADER", "ocp-apim-subscription-key")
    seen: dict = {}
    server = build_server(settings, transport=capture_transport(seen))
    async with Client(server) as client:
        await client.call_tool("claim_history_listClaims", {"memberId": "m-1"})
    assert seen["headers"]["ocp-apim-subscription-key"] == "domain-key"


def test_client_credentials_is_not_implemented(tmp_path):
    settings = make_settings(
        tmp_path,
        auth_mode="client-credentials",
        token_url="https://auth.example/token",
        client_id="id",
        client_secret="secret",
    )
    with pytest.raises(NotImplementedError, match="token URL"):
        build_auth(settings, "claim-history")


async def test_client_credentials_domain_is_skipped(tmp_path, monkeypatch):
    settings = _claim_server(tmp_path, monkeypatch, auth_mode="client-credentials")
    assert await tool_names(build_server(settings)) == []


def test_forward_auth_flow_sets_header(monkeypatch):
    monkeypatch.setattr(
        "pbm_mcp.auth.forward.get_http_request",
        lambda: _Request("Bearer from-request"),
    )
    request = httpx2.Request("GET", "https://claims.test/claims")
    next(ForwardAuth().auth_flow(request))
    assert request.headers["Authorization"] == "Bearer from-request"


async def test_request_url_is_not_logged(tmp_path, monkeypatch, caplog):
    settings = _claim_server(tmp_path, monkeypatch, auth_mode="none")
    seen: dict = {}
    server = build_server(settings, transport=capture_transport(seen))
    caplog.set_level(logging.INFO)
    async with Client(server) as client:
        await client.call_tool("claim_history_listClaims", {"memberId": "m-100"})
    assert "m-100" not in caplog.text
    assert "claims.test" not in caplog.text
    assert "operation=listClaims" in caplog.text


async def test_api_key_without_secret_skips_domain(tmp_path, monkeypatch):
    settings = _claim_server(tmp_path, monkeypatch, auth_mode="api-key", api_key="")
    assert await tool_names(build_server(settings)) == []

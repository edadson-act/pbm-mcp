import pytest
from fastmcp import Client
from mcp.types import LATEST_PROTOCOL_VERSION
from starlette.testclient import TestClient

from pbm_mcp.config import ConfigError, Settings
from pbm_mcp.mcp_auth import inbound_authorization_is_forwarded
from pbm_mcp.server import build_server
from tests.helpers import (
    capture_transport,
    make_settings,
    write_allowlist,
    write_openapi,
)

TOKEN = "mcp-test-token-01"
OTHER = "mcp-test-token-02"

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": LATEST_PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}


def _http_app(tmp_path, token: str = TOKEN):
    settings = make_settings(tmp_path, mcp_bearer_token=token)
    server = build_server(settings)
    return server.http_app(path="/mcp", json_response=True, stateless_http=True)


def _post(client: TestClient, token: str | None):
    headers = {"Accept": "application/json, text/event-stream"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return client.post("/mcp", json=INITIALIZE, headers=headers)


def test_missing_bearer_is_rejected(tmp_path):
    app = _http_app(tmp_path)
    with TestClient(app) as client:
        response = _post(client, None)
    assert response.status_code == 401
    assert TOKEN not in response.text
    assert "bearer" in response.headers["www-authenticate"].lower()


def test_wrong_bearer_is_rejected(tmp_path):
    app = _http_app(tmp_path)
    with TestClient(app) as client:
        response = _post(client, OTHER)
    assert response.status_code == 401
    assert TOKEN not in response.text
    assert OTHER not in response.text
    assert "invalid_token" in response.headers["www-authenticate"]


def test_matching_bearer_reaches_mcp(tmp_path):
    app = _http_app(tmp_path)
    with TestClient(app) as client:
        response = _post(client, TOKEN)
    assert response.status_code == 200
    body = response.json()
    assert body["result"]["serverInfo"]["name"] == "pbm-mcp"


def test_open_endpoint_does_not_require_a_token(tmp_path):
    settings = make_settings(tmp_path, mcp_bearer_token="")
    app = build_server(settings).http_app(
        path="/mcp",
        json_response=True,
        stateless_http=True,
    )
    with TestClient(app) as client:
        response = _post(client, None)
    assert response.status_code == 200


def test_short_token_is_rejected(tmp_path):
    settings = make_settings(tmp_path, mcp_bearer_token="short-token")
    with pytest.raises(ConfigError, match="16 characters"):
        build_server(settings)


def test_bearer_prefix_in_token_is_rejected(tmp_path):
    settings = make_settings(tmp_path, mcp_bearer_token=f"Bearer {TOKEN}")
    with pytest.raises(ConfigError, match="secret only"):
        build_server(settings)


def test_blank_token_leaves_endpoint_open(tmp_path):
    settings = make_settings(tmp_path, mcp_bearer_token="   ")
    assert build_server(settings).auth is None


def test_reachable_host_without_token_is_refused(tmp_path):
    settings = make_settings(tmp_path, host="0.0.0.0")
    with pytest.raises(ConfigError, match="PBM_MCP_BEARER_TOKEN"):
        build_server(settings)


def test_reachable_host_with_token_starts(tmp_path):
    settings = make_settings(tmp_path, host="0.0.0.0", mcp_bearer_token=TOKEN)
    assert build_server(settings).auth is not None


def test_forward_mode_is_detected():
    assert inbound_authorization_is_forwarded(Settings(auth_mode="forward")) is True
    assert inbound_authorization_is_forwarded(Settings(auth_mode="none")) is False


async def test_mcp_bearer_is_not_sent_upstream(tmp_path, monkeypatch):
    monkeypatch.setenv("PBM_CLAIM_HISTORY_BASE_URL", "https://claims.test")
    settings = make_settings(
        tmp_path,
        auth_mode="bearer-env",
        bearer_token="env-token",
        mcp_bearer_token=TOKEN,
    )
    write_openapi(settings, "claim-history")
    write_allowlist(settings, "claim-history", [{"id": "listClaims"}])
    seen: dict = {}
    server = build_server(settings, transport=capture_transport(seen))
    async with Client(server) as client:
        await client.call_tool("claim_history_listClaims", {"memberId": "m-1"})
    assert seen["headers"]["authorization"] == "Bearer env-token"
    assert TOKEN not in seen["headers"]["authorization"]
